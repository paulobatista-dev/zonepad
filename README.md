# ZonaPad

Aplicativo Python para calibrar controles (gamepads) de forma guiada e reproduzível. O MVP atual é Linux-only; portas mantêm o domínio portátil para backends futuros.

> **Estado atual:** MVP Linux com pipeline raw → normalizado → calibrado, replay determinístico, perfis JSON versionados, CLI e GUI Qt opcional.

## Requisitos

- Linux (MVP atual).
- Python 3.15.x. O projeto fixa `3.15.0` em `.tool-versions` e declara
  `requires-python = ">=3.15,<3.16"`.

## Ambiente de desenvolvimento

O projeto usa asdf para a versão do Python e virtualenv para o ambiente.

```bash
asdf plugin add python          # apenas se o plugin ainda não existir
asdf install python 3.15.0      # apenas se a versão ainda não estiver instalada
asdf set python 3.15.0          # grava .tool-versions
python --version                # Python 3.15.0

python -m pip install --user virtualenv   # ou: pipx install virtualenv
python -m virtualenv --python "$(asdf which python)" .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Alternativa sem virtualenv instalado: `python -m venv .venv`, ative e rode
`python -m pip install -e '.[dev]'`.

O extra `dev` instala pytest, ruff, mypy e virtualenv. A CI usa Python 3.15.0
e o mesmo extra.

## Instalação e uso

Dentro de um ambiente com Python 3.15:

```bash
python -m pip install .
zonepad list
zonepad profiles --directory ~/.config/zonepad/profiles
zonepad replay captura.jsonl
zonepad run --device event3 --profile <uuid> --mapping controle.json --duration 10
zonepad measure captura.jsonl --manifest captura.manifest.json --mapping controle.json
```

O backend Linux lê `/dev/input/event*` (evdev), aplica o perfil em tempo real e publica eventos em um controle virtual por `/dev/uinput`. O acesso ao dispositivo `uinput` depende das permissões da distribuição. Nenhum acesso a hardware é executado nos testes.

O runtime programático é exposto por `zonepad.application.runtime.build_runtime`; a CLI cobre descoberta, perfis, replay e execução de perfil salvo. O comando `run` aplica o perfil somente ao controle virtual criado pelo ZonaPad.

### Executar um perfil salvo

`zonepad run` requer um mapping JSON. Embora `--mapping` permaneça opcional para permitir uma mensagem de erro mais clara, o comando encerra com código 2 se ele faltar: o ZonaPad não infere ranges, centro de stick ou repouso de trigger.

```bash
zonepad run \
  --device event3 \
  --profile 550e8400-e29b-41d4-a716-446655440000 \
  --mapping controle.json \
  --profiles-dir ~/.config/zonepad/profiles \
  --duration 10
```

O mapping v1 é estrito: campos desconhecidos, códigos repetidos, valores não inteiros e ranges inválidos são rejeitados. Ele define os códigos evdev e os valores raw medidos; os quatro botões faciais são opcionais.

```json
{
  "schema_version": 1,
  "axes": {
    "lx": {"code": 0, "minimum": -32768, "center": 0, "maximum": 32767},
    "ly": {"code": 1, "minimum": -32768, "center": 0, "maximum": 32767},
    "rx": {"code": 3, "minimum": -32768, "center": 0, "maximum": 32767},
    "ry": {"code": 4, "minimum": -32768, "center": 0, "maximum": 32767}
  },
  "triggers": {
    "lt": {"code": 2, "rest": 0, "maximum": 255},
    "rt": {"code": 5, "rest": 0, "maximum": 255}
  },
  "buttons": {
    "304": "button_south",
    "305": "button_east",
    "307": "button_north",
    "308": "button_west"
  }
}
```

O backend acumula mudanças evdev até `SYN_REPORT`; portanto cada frame publicado representa um pacote completo. Botões físicos que não aparecem no mapping são ignorados. Para acessar `/dev/input/event*` e `/dev/uinput`, configure as permissões da distribuição via grupo apropriado ou regra udev reversível; não execute o aplicativo como root. Falta de permissão em `/dev/uinput` retorna código 3 com essa orientação.

Os frames evdev recebem timestamp do relógio monotônico do host no momento de `SYN_REPORT`; isso mantém a ordem temporal mesmo quando o relógio civil é ajustado. A origem é uma aproximação de leitura, não o timestamp do kernel.

### Medir métricas e gerar um perfil

`zonepad measure` calcula métricas de sticks e triggers a partir de uma captura raw segmentada por um manifesto, emite um relatório (JSON e Markdown) e, com `--save-profile`, grava um perfil `schema_version=1`. O comando não lê `/dev/input` nem `/dev/uinput`; ele só abre os arquivos informados. A spec completa (fórmulas, janelas, mínimos e catálogo de achados) está em [`docs/specs/metrics-v1.md`](docs/specs/metrics-v1.md) e a decisão de contrato em [`docs/adr/0004-metricas-relatorio-separado-e-perfil-v1.md`](docs/adr/0004-metricas-relatorio-separado-e-perfil-v1.md).

```bash
zonepad measure captura.jsonl \
  --manifest captura.manifest.json \
  --mapping controle.json \
  --report metricas.json --report-md metricas.md \
  --save-profile ~/.config/zonepad/profiles
```

**Captura.** JSONL com um frame raw por linha: `device_id`, `timestamp_ns` (inteiro monotônico), `axes`, `triggers` (inteiros) e `buttons` (opcional). O leitor é estrito: rejeita `NaN`/`Infinity`, timestamps float ou decrescentes, `device_id` misto e campos desconhecidos, citando arquivo e linha. A gravação guiada fica para o wizard (prompt 03); por enquanto, a captura vem de qualquer ferramenta que escreva esse formato.

**Protocolo (~85 s).** Aquecimento de 2 s sem tocar (fora de segmento); repouso de 5 s (`rest`, com `warmup_ns` de 1 s); por stick, 3 voltas horárias e 3 anti-horárias na borda do gate (`circle`); por trigger, 5 ciclos de pressionar até o fundo e soltar (`trigger_sweep`). O repouso efetivo precisa de pelo menos 3 s e 150 frames; cada volta, de pelo menos 100 frames.

**Manifesto** (`manifest_version=1`, obrigatório; os segmentos são intervalos `[start_ns, end_ns)`, ordenados e sem sobreposição):

```json
{
  "manifest_version": 1,
  "device": {"device_id": "event3", "name": "Xbox Wireless Controller", "vid": "0x045e", "pid": "0x0b13"},
  "capture_file": "captura.jsonl",
  "nominal_rate_hz": 125,
  "connection": "bluetooth",
  "segments": [
    {"kind": "rest", "start_ns": 2000000000, "end_ns": 7000000000, "warmup_ns": 1000000000},
    {"kind": "circle", "stick": "left", "direction": "cw", "start_ns": 8000000000, "end_ns": 14000000000},
    {"kind": "circle", "stick": "left", "direction": "ccw", "start_ns": 14500000000, "end_ns": 20500000000},
    {"kind": "trigger_sweep", "trigger": "left", "start_ns": 22000000000, "end_ns": 47000000000}
  ]
}
```

Campos opcionais: `capture_sha256`, `nominal_rate_hz`, `connection` (`usb`, `bluetooth`, `wireless_dongle`, `unknown`) e, em `device`, `guid` e `serial`. Campos desconhecidos são rejeitados, e `device.device_id` e `capture_file` precisam coincidir com a captura. `serial` e `guid` entram apenas no perfil local, nunca no relatório.

**Mapping.** `--mapping` é obrigatório e usa o mesmo JSON v1 do `zonepad run`: as métricas são calculadas sobre valores normalizados por ele, o mesmo espaço em que o perfil é aplicado. O `measure` não substitui o mapping do `run`.

**Relatório.** O JSON (`report_kind="calibration-metrics"`, `metrics_schema_version=1`) traz dispositivo, captura (hash SHA-256, frames, taxa efetiva e p5/p95), segmentos, métricas por stick e trigger (valor típico e pior caso), diagnóstico raw, achados de qualidade, o resumo do perfil e os thresholds efetivos. É determinístico para a mesma entrada, serializado com `allow_nan=False` e arredondado a 6 casas. O Markdown é derivado do JSON e não recalcula nada. Sem `--report` e sem `--report-md`, o JSON vai para stdout.

**Achados e `--strict`.** Cada achado tem `code`, `severity` (`info`, `warning`, `error`), `message`, `metric`, `value`, `threshold` e `strict_blocking`; `quality.status` é `fail` com algum `error`, `warn` com algum `warning` e `pass` caso contrário. Com `--strict`, qualquer `error` ou `warning` bloqueante encerra com código 4 e nenhum perfil é gravado.

**Thresholds.** Os defaults são *default a validar*, não valores universais: `drift_max` 0,02; `noise_rms_max` 0,005; `circularity_min` 0,90; `trigger_r2_min` 0,98; `hysteresis_max` 0,03; `rate_tolerance` 0,10; deadzone `max(1,5 × P99 do ruído, piso 0,02)` para sticks e piso 0,01 para triggers. Sobrescreva qualquer valor com `--thresholds` (campos omitidos usam o default; o relatório registra o conjunto efetivo):

```json
{"thresholds_version": 1, "drift_max": 0.03, "deadzone": {"factor": 2.0}, "protocol": {"rest_min_frames": 100}}
```

**Códigos de saída.** `0` relatório gerado (avisos não bloqueiam sem `--strict`); `1` falha inesperada; `2` captura, manifesto, mapping, thresholds ou argumentos inválidos; `4` qualidade insuficiente com `--strict`, ou `--save-profile` sem perfil derivável (o relatório continua sendo escrito).

**Limitações.**

- Linearidade e histerese do trigger usam o tempo normalizado como proxy do curso, pois a captura não tem sensor de posição; os achados correspondentes são `info`.
- O repouso de poucos segundos mede deriva de curto prazo, não deriva térmica; grave um segundo `rest` ao final para ver o deslocamento do centro.
- Deadzone de firmware não é medida; a deadzone sugerida pode somar-se a ela.
- Controles sem trigger analógico (por exemplo, ZL/ZR digitais do Switch Pro) não são suportados no v1: o perfil exige os dois triggers.
- Botões são ignorados, e a comparação entre sessões fica para o wizard.
- Os thresholds e fatores ainda não foram validados com capturas reais de vários controles.
- A captura inteira é carregada em memória (cerca de 10 mil frames por sessão de 85 s a 125 Hz).

Para a GUI, instale o extra opcional: `python -m pip install -e '.[gui]'` (ou `'.[dev,gui]'`) e execute `zonepad-gui`.

## Arquitetura

`zonepad.domain` contém frames imutáveis, normalização, transformações e perfil validado. `zonepad.application` define portas e orquestra leitura. `zonepad.infrastructure` implementa evdev, uinput, replay, fakes e persistência JSON. `zonepad.interface` fornece CLI e GUI opcional.

Perfis são salvos atomicamente em JSON com `schema_version=1`; campos desconhecidos, ranges inválidos, UUIDs não-v4 e números não finitos são rejeitados.

## O que existe

- **3 agentes especialistas** com escopo, processo, contrato de saída e handoffs.
- **12 skills** com procedimentos e referências progressivas.
- **4 fluxos** multiagente para bootstrap, design, implementação e revisão.
- **Fonte canônica única** em `ai/`, espelhada para OpenCode, Claude Code e Codex.
- **Gerador idempotente** com validação `--check` para CI.

## Estrutura

```text
.
├── ai/                          # fonte canônica (edite aqui)
│   ├── agents/<id>/             # agent.json + prompt.md
│   ├── skills/<id>/             # SKILL.md + references/scripts/assets
│   ├── flows/<id>/              # flow.json + FLOW.md
│   ├── prompts/                 # prompts de implementação
│   └── instructions/AGENTS.md
├── scripts/
│   └── sync_ai_assets.py        # gera os espelhos
├── tests/
│   └── test_sync_ai_assets.py
├── .tool-versions               # versão do Python para asdf
├── .opencode/                   # gerado: agentes, skills, comandos
├── .claude/                     # gerado: agentes, skills
├── .agents/                     # gerado: skills (Codex)
├── .codex/                      # gerado: agentes TOML
├── AGENTS.md                    # gerado: OpenCode/Codex
├── CLAUDE.md                    # gerado: Claude Code
├── LICENSE                      # licença MIT
└── README.md                    # visão geral, uso e arquitetura
```

## Fonte canônica

Nunca edite `.opencode/`, `.claude/`, `.agents/`, `.codex/`, `AGENTS.md` ou `CLAUDE.md`. Eles são gerados e sobrescritos.

Fluxo de trabalho:

```bash
# 1. edite ai/
# 2. gere os espelhos
python scripts/sync_ai_assets.py

# 3. valide antes de concluir
python scripts/sync_ai_assets.py --check
python -m pytest -q
```

## Agentes

| Agente | Especialidade | Skills principais |
| --- | --- | --- |
| `prompt-engineer` | Prompts, skills, fluxos, avaliação e custo de contexto. | `prompt-design`, `prompt-evaluation`, `positive-ontology`, `evidence-based`, `github-interaction` |
| `python-engineer` | Arquitetura, código, testes, tipagem e packaging. | `python-app-architecture`, `python-quality`, `clean-code`, `clean-architecture`, `calibration-domain`, `evidence-based`, `github-interaction` |
| `controller-hardware` | HID/SDL3, protocolos, medição e calibração. | `controller-protocols`, `calibration-metrics`, `calibration-domain`, `positive-ontology`, `evidence-based` |

Como acionar:

- **OpenCode:** peça ao agente principal para usar o subagente (`prompt-engineer`, `python-engineer` ou `controller-hardware`).
- **Claude Code:** peça "use o subagente `python-engineer`" ou confie na delegação automática pela descrição.
- **Codex:** peça "use o agente `controller-hardware`" ou solicite subagentes em paralelo.

## Skills

| Skill | Dono | Quando usar |
| --- | --- | --- |
| `prompt-design` | prompt-engineer | Criar/revisar agente, skill ou fluxo. |
| `positive-ontology` | prompt-engineer / hardware | Definir comportamentos e critérios de forma afirmativa e observável. |
| `prompt-evaluation` | prompt-engineer | Testar disparo, regressão e qualidade de prompt. |
| `evidence-based` | compartilhada | Separar fato, inferência, suposição e recomendação; exigir evidência. |
| `python-app-architecture` | python-engineer | Decidir camadas, portas e fluxo de dados no ZonaPad. |
| `clean-code` | python-engineer | Nomes, funções, erros, testes e legibilidade do código. |
| `clean-architecture` | python-engineer | Regra de dependência, boundaries, portas e adaptadores. |
| `python-quality` | python-engineer | Testes, lint, tipos, CI e performance. |
| `controller-protocols` | controller-hardware | Integrar dispositivo e interpretar relatórios. |
| `calibration-metrics` | controller-hardware | Medir e definir critérios de calibração. |
| `calibration-domain` | compartilhada | Modelo de frames, pipeline e schema de perfil. |
| `github-interaction` | compartilhada | Inspecionar repo, issues, PRs, checks, releases e Actions com segurança. |

Invocação:

- **OpenCode:** `@prompt-design` ou carregamento automático pela descrição.
- **Claude Code:** `/prompt-design` ou carregamento automático.
- **Codex:** `$prompt-design` ou carregamento automático.

## Fluxos

| Fluxo | Objetivo |
| --- | --- |
| `flow-bootstrap-app` | Criar MVP, arquitetura, contratos, esqueleto, README e licença. |
| `flow-design-feature` | Especificar uma feature antes de codar. |
| `flow-implement-feature` | Implementar uma spec aprovada com testes e revisão. |
| `flow-review-calibration` | Revisão multiagente de código e medições. |

Invocação:

- **OpenCode:** `/flow-bootstrap-app` ou `@flow-bootstrap-app`.
- **Claude Code:** `/flow-bootstrap-app`.
- **Codex:** `$flow-bootstrap-app`.

## Prompts de implementação

Prompts versionados em `ai/prompts/` para executar incrementos no Claude Code ou Codex. Eles não são espelhados pelo gerador.

- `00-toolchain-python-315-asdf-virtualenv.md` é pré-requisito do `01-runtime-cli-end-to-end.md`: fixa Python 3.15.0 (asdf), virtualenv, `pyproject.toml` e CI.
- **Claude Code:** referencie `@ai/prompts/00-toolchain-python-315-asdf-virtualenv.md` e depois `@ai/prompts/01-runtime-cli-end-to-end.md`.
- **Codex:** referencie `ai/prompts/00-toolchain-python-315-asdf-virtualenv.md` e depois `ai/prompts/01-runtime-cli-end-to-end.md`, ou cole o conteúdo.
- O primeiro incremento de runtime é o comando `zonepad run` com evdev → perfil → uinput.

## GitHub

A skill `github-interaction` cobre diagnóstico, issues, branches, commits, pull requests, checks, revisões, releases e GitHub Actions.

Pré-requisito: `gh auth status` deve indicar autenticação. Se o GitHub CLI não estiver instalado, instale `gh` e rode `gh auth login` em um terminal interativo. Operações de escrita exigem intenção explícita; merge e ações destrutivas são confirmados antes de executar.

## Como funciona o espelhamento

| Conceito | OpenCode | Claude Code | Codex |
| --- | --- | --- | --- |
| Instruções | `AGENTS.md` | `CLAUDE.md` | `AGENTS.md` |
| Skills | `.opencode/skills/` | `.claude/skills/` | `.agents/skills/` |
| Agentes | `.opencode/agents/*.md` | `.claude/agents/*.md` | `.codex/agents/*.toml` |
| Fluxos | `.opencode/skills/` + `.opencode/commands/` | `.claude/skills/` | `.agents/skills/` |

O gerador:

1. Lê os metadados JSON e os corpos Markdown de `ai/`.
2. Converte os agentes para os três schemas (Markdown/YAML e TOML).
3. Copia skills canônicas e gera as skills de fluxo.
4. Gera comandos `/flow-...` para OpenCode.
5. Gera `agents/openai.yaml` para desabilitar invocação implícita dos fluxos no Codex.
6. Mantém um manifesto `.generated.json` em cada destino e remove arquivos obsoletos.
7. Compara tudo em `--check` sem escrever.

> **Escopo:** os espelhos são do projeto. Para uso global, copie os diretórios gerados para `~/.config/opencode/`, `~/.claude/` e `~/.agents/`/`~/.codex/`, conforme a ferramenta.

## Adicionar um agente

1. Crie `ai/agents/<id>/agent.json` e `prompt.md`.
2. Use as chaves `name`, `description`, `tools`, `skills`, `models`, `reasoning_effort` e `color`.
3. Rode o gerador e confira os três espelhos.
4. Adicione casos de avaliação em `ai/skills/prompt-evaluation/references/test-matrix.md`.

## Adicionar uma skill

1. Crie `ai/skills/<id>/SKILL.md` com frontmatter `name` e `description`.
2. Mantenha o nome igual ao diretório, em kebab-case.
3. Mova conteúdo extenso para `references/`.
4. Declare a skill em `skills` do agente que deve usá-la.

## Adicionar um fluxo

1. Crie `ai/flows/flow-<id>/flow.json` e `FLOW.md`.
2. `FLOW.md` contém apenas o corpo, sem frontmatter.
3. O fluxo é gerado como skill com `disable-model-invocation: true`.
4. No Codex, invoque com `$flow-<id>`; nos demais, `/flow-<id>`.

## Compatibilidade e limites

- Skills seguem o padrão [Agent Skills](https://agentskills.io/specification), mas cada ferramenta tem extensões próprias.
- Agentes **não** são portáveis byte a byte: OpenCode usa `permissions`, Claude usa `tools`/`skills` e Codex usa TOML. O gerador traduz o subconjunto comum.
- O Codex não aplica restrições de ferramenta por agente além de feature toggles; as regras de escopo são comportamentais.
- Prompts customizados do Codex estão deprecated e são globais; por isso os fluxos são skills explícitas.
- O Claude pré-carrega as skills listadas em `skills` no subagente; isso consome contexto.
- O OpenCode não cria slash commands a partir de skills; os comandos de fluxo são gerados separadamente.
- Skills são copiadas para três diretórios. Edite sempre `ai/`.

## Validação

```bash
python -m pytest -q
python -m ruff check .
python -m mypy src/zonepad
python scripts/sync_ai_assets.py --check
```

A CI em `.github/workflows/ai-assets.yml` usa Python 3.15.0, instala `.[dev]` e roda esses quatro comandos.

## Licença

Distribuído sob a licença MIT. Veja [LICENSE](LICENSE).

Copyright (c) 2026 ZonaPad contributors.

## Próximos passos

1. Medir e versionar mappings por família de controle, USB/Bluetooth e firmware.
2. Adicionar o wizard guiado de calibração sobre `zonepad measure` (gravação da captura e do manifesto).
3. Implementar descoberta hot-plug e parsers específicos após capturas reais.
