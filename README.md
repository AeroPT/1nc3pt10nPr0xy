# 1nc3pt10nPr0xy
Washing Machine Technical Manual

# InceptionProxy 🚀

Um proxy API robusto e headless, desenvolvido em Python, que interceta pedidos de chat completion no padrão OpenAI e encaminha-os dinamicamente através de uma instância Chromium controlada por Playwright, utilizando a interface de chat da InceptionLabs.

Expõe um servidor web compatível com OpenAI (`/v1/chat/completions`), processa payloads multimodais/estruturados de forma nativa (sendo totalmente compatível com clientes de terminal como `pi.dev`) e inclui uma interface CLI de arranque minimalista e moderna.

---

## 🛠️ Principais Funcionalidades Arquiteturais

* **Compatibilidade com o Contrato OpenAI:** Expõe os endpoints `/v1/models` e `/v1/chat/completions`, funcionando como substituto direto para qualquer cliente OpenAI padrão ou interface local.
* **Parser de Payloads de Alta Tolerância:** Processa sem problemas tanto strings de texto simples (ex.: pedidos curl ou PowerShell) como listas estruturadas de mensagens contendo blocos (`{"type": "text", "text": "..."}`) geradas por clientes de terminal avançados.
* **Injeção da Política Event Loop no Windows:** Força automaticamente `WindowsSelectorEventLoopPolicy` em sistemas Win32 diretamente no entrypoint, garantindo o rastreamento assíncrono nativo de subprocessos necessário ao Playwright.
* **Ativação Reativa do Estado JS:** Evita injeções primitivas no DOM (`page.fill()`), que normalmente ignoram listeners de virtual DOM em aplicações SPA. Em vez disso, utiliza simulação física de teclado (`page.keyboard.type()`) com delays explícitos para acionar corretamente a reatividade `onChange`.
* **Sincronização de Estado Thread-Safe:** Implementa um gestor de estado assíncrono protegido por `asyncio.Lock`, preservando um histórico linear rigoroso entre pedidos HTTP sequenciais.
* **Mapeamento de Interfaces Sem Overhead de Rede:** Utiliza `psutil` para inspecionar dinamicamente as tabelas de interfaces de rede (`net_if_addrs`), extraindo endereços IPv4 físicos e Tailscale VPN sem depender de handshakes DNS externos.
* **Bootstrapper Minimalista do Framework:** Silencia os logs padrão do Uvicorn (`log_config=None`) para apresentar uma interface de estado elegante durante o arranque do proxy.

---

## 🏗️ Fluxo da Arquitetura

1. **Inicialização:** A aplicação integra-se no context manager `lifespan` do FastAPI, inicia um processo Chromium headless via Playwright, navega até ao endpoint alvo e aguarda até o DOM estabilizar.
2. **Receção de Pedidos:** O proxy interceta pedidos POST recebidos em `/v1/chat/completions`. Caso seja passado o parâmetro `stream`, utiliza um gerador SSE (Server-Sent Events) simulado.
3. **Automação DOM & Limpeza do Input:** O lock de thread é ativado. O seletor de input é focado e totalmente limpo através de atalhos específicos da plataforma (`Control+A` / `Meta+A` + `Backspace`).
4. **Simulação de Escrita & Submissão:** A mensagem é escrita no elemento com um delay de 10ms entre caracteres para satisfazer os listeners de eventos de input. Depois é enviado um `Enter` virtual.
5. **Polling de Alterações no DOM:** Um sistema de polling altamente responsivo monitoriza o número de wrappers alvo (`.prose-chat`) no DOM. Assim que é detetado um delta de `+1`, captura o texto interno, aguarda estabilização completa da resposta e desbloqueia o lock.
6. **Encapsulamento do Payload:** A string final extraída é encapsulada num schema de resposta OpenAI válido (`choices[0].message.content`) e devolvida ao cliente.

---

## 📦 Pré-requisitos & Instalação

### 1. Clonagem & Configuração do Ambiente
Certifica-te de que estás a usar Python 3.10 ou superior. Navega até à pasta do projeto e cria um ambiente virtual:

```powershell
# Criar ambiente virtual
python -m venv venv

# Ativar no Windows (PowerShell)
.\venv\Scripts\Activate.ps1
```

### 2. Instalação de Dependências
Instala os wrappers assíncronos de rede, drivers de automação e utilitários de monitorização necessários:

```bash
pip install fastapi uvicorn pydantic playwright psutil
```

### 3. Instalação dos Binários do Playwright
Instala os binários standalone do Chromium no cache local:

```bash
playwright install chromium
```

---

## 🚀 Execução

Executa o ficheiro principal assíncrono:

```bash
python inceptionproxy.py
```

Após iniciar, o proxy irá detetar automaticamente os adaptadores disponíveis e apresentar a matriz de runtime personalizada:

```text
🚀 InceptionProxy iniciado!
  - Local:   http://localhost:3000
  - Rede:    http://100.66.114.104:3000

A inicializar o Playwright e o motor Chromium...
A navegar para o alvo e a aguardar estabilização do DOM...
Proxy totalmente operacional.
```

---

## 🔌 Especificação da API & Testes

### 1. Listar Modelos
Verifica a integridade da ligação cliente-proxy.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:3000/v1/models" -Method Get
```

### 2. Chat Completions (Texto Simples)
Simula um pedido clássico via terminal.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:3000/v1/chat/completions" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"model": "inception-chat", "messages": [{"role": "user", "content": "Conta uma piada sobre programadores"}]}'
```

### 3. Chat Completions (Conteúdo Estruturado)
Simula clientes avançados (`pi.dev` formato runtime multimodal).

```json
{
  "model": "inception-chat",
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "Explica de forma curta a diferença entre stack e heap."
        }
      ]
    }
  ]
}
```

---

## 🛡️ Licença

Utilitário técnico interno. Protegido por design. Minimalismo funcional acima de marketing desnecessário.
