# Diretrizes Técnicas de Rede e API Gemini (Metrics Analyzer)

## 1. Conexões de Rede em Python no Linux (Fast-Path IPv4)
- Sempre force `urllib3` a priorizar IPv4 (`socket.AF_INET`) em chamadas HTTP/REST:
  ```python
  import socket
  import urllib3.util.connection as urllib3_conn

  urllib3_conn.allowed_gai_family = lambda: socket.AF_INET
  ```
  *Motivo*: Ambientes Linux com IPv6 habilitado localmente sem rota WAN externa ativa causam timeouts silenciosos de 15s a 60s por requisição no `requests`/`urllib3`.
- Sempre utilize `requests.Session()` com reuso de conexões TLS persistentes em vez de funções soltas `requests.post()` ou `requests.get()`.

## 2. Chamadas de Streaming SSE com Google Gemini 3.x / Flash
- Em requisições de Streaming SSE (`:streamGenerateContent?alt=sse`) com `thinkingConfig`, **sempre inclua `"includeThoughts": True`**.
  *Motivo*: O gateway REST do Google segura o status `HTTP 200 OK` até o 1º frame SSE; sem pensamentos habilitados, a requisição trava esperando todo o raciocínio concluir.
- No consumo do SSE, filtre os blocos com `p.get("thought")` para cronometrar a fase de raciocínio e nunca misturar o rascunho mental no texto final do usuário.
- Transmita os chunks de texto imediatamente para o cliente/navegador para garantir Time-To-First-Token (TTFT) abaixo de 3 segundos.
