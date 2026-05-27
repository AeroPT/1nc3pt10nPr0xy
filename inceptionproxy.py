import asyncio
import sys
import uuid
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from playwright.async_api import async_playwright

# --- 1. INJEÇÃO DA POLÍTICA OBRIGATÓRIA PARA O PLAYWRIGHT NO WINDOWS ---
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- 2. CONFIGURAÇÃO DE ESTADO E COORDENADAS ---
state = {
    "playwright": None,
    "browser": None,
    "page": None,
    "lock": asyncio.Lock()  # Garante linearidade no histórico do chat remoto
}

URL_ALVO = "https://chat.inceptionlabs.ai/"
SELECTOR_INPUT = "textarea[placeholder='How can I help you?']"
SELECTOR_SUBMIT = "button[type='submit'][aria-label='Send message']"
SELECTOR_MESSAGES = ".prose-chat"

# --- 3. MODELO DE DADOS DE ALTA TOLERÂNCIA ---
class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str
    messages: list[dict]
    stream: bool = False

# --- 4. LIFESPAN (DEFINIDO ANTES DE SER USADO NO FASTAPI) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gere o ciclo de vida da API e do browser em background."""
    print("A inicializar o Playwright e o motor Chromium...")
    state["playwright"] = await async_playwright().start()
    state["browser"] = await state["playwright"].chromium.launch(headless=True)
    state["page"] = await state["browser"].new_page()
    
    print("A navegar para o alvo e a aguardar estabilização do DOM...")
    try:
        await state["page"].goto(URL_ALVO)
        await state["page"].wait_for_selector(SELECTOR_INPUT, timeout=30000)
        print("Proxy totalmente operacional.")
    except Exception as e:
        print(f"Erro crítico na inicialização do browser: {e}")
        
    yield
    
    print("A encerrar o servidor. A libertar recursos do Browser...")
    if state["page"]: await state["page"].close()
    if state["browser"]: await state["browser"].close()
    if state["playwright"]: await state["playwright"].stop()

# --- 5. INICIALIZAÇÃO DA APP FASTAPI ---
app = FastAPI(title="InceptionLabs API Proxy", lifespan=lifespan)

# --- 6. MÉTODOS AUXILIARES E ENDPOINTS ---
async def get_last_message_count(page) -> int:
    return len(await page.query_selector_all(SELECTOR_MESSAGES))

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{"id": "inception-chat", "object": "model", "created": 1716812400, "owned_by": "inceptionlabs"}]
    }

@app.post("/v1/chat/completions")
async def chat_proxy(payload: ChatRequest):
    if not state["page"]:
        raise HTTPException(status_code=500, detail="Instância do browser offline.")
    if not payload.messages:
        raise HTTPException(status_code=400, detail="O array de mensagens não pode estar vazio.")
    
    last_msg = payload.messages[-1]
    raw_content = last_msg.get("content", "")
    
    user_message = ""
    if isinstance(raw_content, str):
        user_message = raw_content
    elif isinstance(raw_content, list):
        for part in raw_content:
            if isinstance(part, dict) and part.get("type") == "text":
                user_message += part.get("text", "")
                
    if not user_message:
        raise HTTPException(status_code=400, detail="Não foi possível extrair texto válido.")

    chat_id = f"chatcmpl-{uuid.uuid4()}"

    async with state["lock"]:
        try:
            page = state["page"]
            initial_count = await get_last_message_count(page)

            await page.wait_for_selector(SELECTOR_INPUT, timeout=5000)
            await page.focus(SELECTOR_INPUT)
            await page.keyboard.press("Control+A" if sys.platform != "darwin" else "Meta+A")
            await page.keyboard.press("Backspace")
            
            await page.keyboard.type(user_message, delay=10)
            await asyncio.sleep(0.5)
            await page.keyboard.press("Enter")

            target_count = initial_count + 1
            for _ in range(60): 
                await asyncio.sleep(1)
                current_count = await get_last_message_count(page)
                if current_count >= target_count:
                    await asyncio.sleep(2)
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    break
            else:
                raise HTTPException(status_code=504, detail="Timeout: O motor remoto não respondeu.")

            messages = await page.query_selector_all(SELECTOR_MESSAGES)
            last_response_element = messages[-1]
            
            response_text = ""
            for _ in range(10):
                response_text = (await last_response_element.inner_text()).strip()
                if response_text:
                    break
                await asyncio.sleep(0.5)

            if not response_text:
                raise HTTPException(status_code=500, detail="Resposta capturada vazia.")

            if payload.stream:
                async def fake_stream_generator():
                    chunk = {
                        "id": chat_id, 
                        "object": "chat.completion.chunk", 
                        "created": 1716812400, 
                        "model": payload.model,
                        "choices": [{"index": 0, "delta": {"role": "assistant", "content": response_text}, "finish_reason": None}]
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
                    
                    final_chunk = {
                        "id": chat_id, 
                        "object": "chat.completion.chunk", 
                        "created": 1716812400, 
                        "model": payload.model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                    }
                    yield f"data: {json.dumps(final_chunk)}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(fake_stream_generator(), media_type="text/event-stream")

            return {
                "id": chat_id,
                "object": "chat.completion",
                "created": 1716812400,
                "model": payload.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": response_text},
                        "finish_reason": "stop"
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            }

        except Exception as e:
            import traceback
            print("\n[ERRO DE EXECUÇÃO NO PROXY]")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Falha na automação do Proxy: {str(e)}")

# --- 7. BLOCO DE EXECUÇÃO DIRETA ---
if __name__ == "__main__":
    import uvicorn
    import psutil
    
    PORT = 3000
    
    def get_network_ips():
        ips = {"tailscale": None, "local": None}
        interfaces = psutil.net_if_addrs()
        
        for iface_name, iface_addresses in interfaces.items():
            for addr in iface_addresses:
                # Filtrar apenas por IPv4 e ignorar o localhost (127.0.0.1)
                if addr.family == 2 and not addr.address.startswith("127."):
                    name_lower = iface_name.lower()
                    # Identifica explicitamente o adaptador da Tailscale
                    if "tailscale" in name_lower or "zt" in name_lower:
                        ips["tailscale"] = addr.address
                    # Identifica adaptadores normais de rede (Wi-Fi, Ethernet)
                    elif "wi-fi" in name_lower or "ethernet" in name_lower or "local" in name_lower:
                        ips["local"] = addr.address
                    # Fallback caso os nomes sejam genéricos (ex: "vEthernet" ou "Conexão rede")
                    elif not ips["local"]:
                        ips["local"] = addr.address
        return ips

    net_ips = get_network_ips()
    
    # Define qual IP mostrar no banner da rede (prioridade para Tailscale)
    network_display = net_ips["tailscale"] or net_ips["local"]
    
    # Teu banner customizado e limpo
    print("\n🚀 InceptionProxy started!")
    print(f"  - Local:   http://localhost:{PORT}")
    if network_display:
        print(f"  - Network: http://{network_display}:{PORT}\n")
    else:
        print("  - Network: Indisponível\n")

    # Escuta em todas as interfaces para aceitar conexões locais e da VPN
    uvicorn.run(
        "app:app", 
        host="0.0.0.0", 
        port=PORT, 
        reload=False, 
        log_config=None
    )