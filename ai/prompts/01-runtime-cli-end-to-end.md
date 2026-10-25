# Prompt 01 — Runtime CLI end-to-end

## Missão

Implemente o primeiro fluxo executável ponta a ponta do ZonaPad no Linux:

```text
evdev → normalização → perfil → uinput
```

O resultado deve ser um comando `zonepad run` que lê um controle físico, aplica um perfil salvo e publica os eventos calibrados em um controle virtual.

## Contexto atual

Leia antes de editar:

- `AGENTS.md`
- `README.md`
- `docs/adr/0002-arquitetura-mvp-linux.md`
- `src/zonepad/application/runtime.py`
- `src/zonepad/application/ports.py`
- `src/zonepad/infrastructure/evdev.py`
- `src/zonepad/infrastructure/uinput.py`
- `src/zonepad/infrastructure/json_profile_store.py`
- `src/zonepad/infrastructure/fake.py`
- `src/zonepad/interface/cli.py`
- `tests/`

O runtime já existe como `run_saved_profile`, mas ainda não há comando de CLI, fonte de ranges raw nem mapeamento de botões.

## Objetivo

Adicionar o subcomando:

```bash
zonepad run \
  --device event3 \
  --profile <uuid> \
  --profiles-dir ~/.config/zonepad/profiles \
  [--mapping dispositivo.json] \
  [--uinput /dev/uinput] \
  [--timeout 0.05] \
  [--duration 10]
```

Comportamento:

1. Validar argumentos e carregar o perfil.
2. Abrir o dispositivo evdev.
3. Obter os ranges raw de eixos e triggers.
4. Criar o publisher uinput.
5. Processar frames até `--duration`, desconexão ou Ctrl+C.
6. Fechar sessão e publisher em qualquer caminho de saída.
7. Sair com código e mensagem acionáveis em caso de erro.

## Escopo

### CLI

- Adicionar `run` ao parser em `src/zonepad/interface/cli.py`.
- `--device` e `--profile` são obrigatórios.
- `--profiles-dir` usa o mesmo default de `profiles`.
- `--timeout` é positivo.
- `--duration` é opcional e positivo; sem ele, rodar até desconexão/Ctrl+C.
- `--mapping` é opcional.
- `--uinput` é opcional; útil para testes e ambientes alternativos.

### Composição testável

Não instancie hardware diretamente dentro do loop. Crie uma função de composição que receba portas:

```python
def build_runtime(
    backend: DeviceBackend,
    store: ProfileStore,
    publisher: FramePublisher,
    device_id: str,
    profile_id: str,
    timeout_s: float,
) -> RuntimeProcessor: ...
```

O `main` da CLI monta as implementações reais; os testes montam fakes.

### Ranges raw

O runtime precisa de `AxisRange` e `TriggerRange` em counts do dispositivo.

Prefira ler os ranges do próprio evdev com `EVIOCGABS` para cada código de eixo/trigger. Se isso não for viável no escopo, implemente um mapping JSON validado e documente a decisão em ADR.

O mapping deve cobrir, no mínimo:

- códigos de eixos (`0`, `1`, `3`, `4` por padrão);
- códigos de triggers (`2`, `5` por padrão);
- ranges raw de eixos (`minimum`, `center`, `maximum`);
- ranges raw de triggers (`rest`, `maximum`);
- mapeamento de botões evdev para nomes semânticos do uinput.

Se usar mapping JSON, valide tipos, ranges, códigos duplicados e campos desconhecidos. Não use `eval`.

### Botões

O backend evdev hoje nomeia botões como `button_<code>`, enquanto o uinput publica nomes como `button_south`. Corrija o caminho para que, com o mapping fornecido:

- os quatro botões faciais sejam publicados no controle virtual;
- botões não mapeados sejam ignorados com segurança;
- o comportamento esteja documentado.

Não é necessário cobrir todos os botões do mercado neste incremento.

### Erros e saída

Mensagens claras e sem stack trace para o usuário:

| Situação | Comportamento |
| --- | --- |
| Perfil inexistente/inválido | mensagem + exit 2 |
| Dispositivo inexistente | mensagem + exit 2 |
| `/dev/uinput` sem permissão | mensagem com dica de udev/grupo + exit 3 |
| Desconexão | mensagem + shutdown limpo |
| Ctrl+C | shutdown limpo + exit 0 |
| Mapping inválido | mensagem + exit 2 |

Não logue cada frame. Logue apenas início, configuração efetiva, desconexão e encerramento.

## Critérios de aceite

- [ ] `zonepad run --help` documenta todos os argumentos.
- [ ] O comando funciona com um dispositivo real Linux e publica eixos/triggers calibrados no uinput.
- [ ] Os quatro botões faciais são publicados quando o mapping os define.
- [ ] `--duration` encerra o comando de forma limpa.
- [ ] Ctrl+C e desconexão fecham sessão e publisher.
- [ ] Perfil, dispositivo, mapping e uinput têm erros acionáveis.
- [ ] O caminho de composição é testável sem hardware.
- [ ] Não há lógica de calibração nova na CLI; ela apenas compõe e apresenta.
- [ ] O domínio permanece sem imports de Linux, evdev, uinput ou CLI.

## Testes obrigatórios

- Parser: argumentos obrigatórios, default de `--profiles-dir`, validação de `--timeout`/`--duration`.
- Composição: `build_runtime` com `FakeBackend`, perfil válido e publisher fake.
- Execução: `--duration` ou limite de frames processa e publica os frames esperados.
- Erros: perfil inexistente, dispositivo inexistente, mapping inválido e publisher indisponível.
- Botões: mapping converte códigos evdev para nomes esperados; código não mapeado é ignorado.
- Ranges: mapping inválido é rejeitado; ranges válidos normalizam corretamente.
- Nenhum teste acessa `/dev/input` ou `/dev/uinput`.

Use `pytest`, `tmp_path` e `capsys`. Não use `sleep` real.

## Fora de escopo

- Wizard de calibração.
- Métricas de ruído, drift, deadzone, circularidade, linearidade ou histerese.
- Descoberta/filtragem de gamepads por VID/PID/capabilities.
- Hot-plug.
- GUI.
- Suporte a Windows/macOS.
- Alterar o schema do perfil, salvo se estritamente necessário; nesse caso, proponha ADR e migração.

## Validação

Execute e reporte:

```bash
python -m pytest -q
ruff check .
mypy src/zonepad
python scripts/sync_ai_assets.py --check
```

Se o ambiente não tiver as ferramentas, use um venv temporário ou declare o que não foi executado.

Smoke manual (se houver controle):

```bash
sudo chmod ... # não faça isso sem explicar; prefira grupo/udev
zonepad list
zonepad run --device eventN --profile <uuid> --mapping dispositivo.json --duration 5
```

Não execute `sudo` sem confirmação. Não altere permissões do sistema sem explicar impacto e reversão.

## Documentação

Atualize:

- `README.md`: uso do `zonepad run`, permissões de `/dev/input` e `/dev/uinput`, formato do mapping (se existir), limitações.
- `docs/adr/`: ADR se a fonte de ranges ou o schema de mapping mudar contrato.
- `ai/prompts/README.md`: marque este prompt como executado, se o fluxo do projeto pedir.

## Formato de saída

Responda em PT-BR com:

1. **Plano** — 2–5 bullets.
2. **Mudanças** — arquivos e contratos.
3. **Testes** — comandos e resultados.
4. **Smoke manual** — o que foi testado e o que não foi.
5. **Riscos** — limitações e próximos passos.

## Invocação

### Claude Code

```text
Use o prompt em @ai/prompts/01-runtime-cli-end-to-end.md.
Leia o arquivo inteiro e implemente o escopo. Use o subagente python-engineer
para o código e peça revisão ao controller-hardware para a parte evdev/uinput.
```

### Codex

```text
Siga o prompt em ai/prompts/01-runtime-cli-end-to-end.md.
Leia o arquivo inteiro e implemente o escopo. Use o agente python-engineer
para o código e peça revisão ao controller-hardware para a parte evdev/uinput.
```
