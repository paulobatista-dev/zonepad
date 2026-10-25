# Prompt 02 — Métricas de calibração e profile builder

- **Status:** pronto para Claude Code (prioridade) e Codex (alternativa).
- **Incremento:** motor de medição, relatório de métricas e geração de perfil a partir de uma captura.
- **Branch de implementação:** `feat/calibration-metrics`, criada a partir de `main`.
- **Fluxos:** `/flow-design-feature` → `/flow-implement-feature` → `/flow-review-calibration`.
- **Agentes:** `controller-hardware` (semântica de medição), `python-engineer` (implementação), `prompt-engineer` (apenas `ai/` e consistência) e Claude principal (orquestração).
- **Fora deste incremento:** wizard interativo, GUI, descoberta/hot-plug e mapeamento automático. O wizard é o **prompt 03**.

## Missão

Entregar o motor de medição do ZonaPad: calcular métricas de sticks e triggers a partir de uma captura raw, emitir um relatório verificável e gerar um perfil de calibração válido com `schema_version=1`.

O resultado deve permitir que uma pessoa execute:

```bash
zonepad measure captura.jsonl --manifest captura.manifest.json \
  --report metricas.json --report-md metricas.md \
  --save-profile ~/.config/zonepad/profiles
```

e obtenha relatório + perfil sem hardware na CI e sem alterar o runtime existente.

Este incremento **não** entrega a experiência guiada de calibração. Ele entrega o motor que o wizard do prompt 03 vai orquestrar.

## Resultado esperado

1. Métricas de domínio puras, testadas e documentadas, com camada e unidade declaradas.
2. Protocolo de captura formalizado em spec, com segmentos e mínimos de amostra.
3. Leitura validada de captura JSONL + manifesto de segmentos.
4. `build_profile_from_metrics` gerando perfil que passa em `validate_profile`.
5. Subcomando aditivo `zonepad measure` com relatório JSON, Markdown e perfil opcional.
6. Testes sintéticos e replay, sem `/dev/input`, `/dev/uinput` ou `sudo`.
7. README e ADR atualizados quando houver decisão de contrato.

## Contexto verificado (2026-10-24)

Revalide no checkout principal, com working tree limpo. Os gates da seção **Validação** são a fonte de verdade.

| Verificação | Resultado |
| --- | --- |
| `main` | prompts 00 e 01 mergeados (PRs #2 e #3); HEAD `03a1af9` |
| Runtime | `zonepad run` funciona com mapping JSON v1, evdev e uinput |
| `src/zonepad/application/calibration.py` | `build_profile` usa média/min/max; não calcula deadzone, ruído, drift, circularidade, linearidade nem histerese |
| Módulo de métricas | inexistente |
| Captura | JSONL lido por `infrastructure/replay.py` com `device_id`, `timestamp_ns`, `axes`, `triggers`, `buttons`; sem rótulo de segmento |
| Perfil | `schema_version=1`; campos desconhecidos, UUID não-v4, números não finitos e ranges inválidos são rejeitados |
| Skills | `calibration-metrics`, `calibration-domain`, `python-app-architecture`, `python-quality`, `clean-code`, `clean-architecture`, `evidence-based` existem em `ai/skills/` |
| CLI | subcomandos `list`, `replay`, `profiles`, `run`; `run` é o único que usa hardware |

## Pré-condições

1. Este prompt deve estar mergeado em `main` antes da implementação. Enquanto não estiver, execute no checkout principal a partir da branch que contém o prompt e registre a exceção no relatório.
2. No checkout principal, crie a branch `feat/calibration-metrics` a partir da `main`:

```bash
cd /home/costa/Workspace/zonepad
git status --porcelain        # deve estar vazio
git switch main
git pull --ff-only
git switch -c feat/calibration-metrics
```

3. Toolchain obrigatória:

```bash
asdf current python        # deve mostrar 3.15.0
python --version           # Python 3.15.0
```

Se `asdf current python` não mostrar `3.15.0`, pare e reporte; não instale outra versão sem pedido.

4. Ambiente:

```bash
python -m venv .venv          # ou: virtualenv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q           # baseline verde antes de editar
```

5. Gates de entrada:

```bash
git status --porcelain        # vazio
git branch --show-current     # feat/calibration-metrics
git log --oneline main..HEAD  # vazio no início
```

Se qualquer gate falhar, pare e peça um checkout principal limpo.

6. Regras de segurança e git:

- Trabalhe no checkout principal. Não use `git worktree` e não edite arquivos gerados (`AGENTS.md`, `CLAUDE.md`, `.opencode/`, `.claude/`, `.agents/`, `.codex/`).
- Não toque na branch `feat/runtime-cli-end-to-end`.
- Não use `git stash`, `git reset`, `git checkout --`, `git restore`, `git rebase`, `git push --force` nem `sudo`.
- Commit local na branch de trabalho é permitido; push, PR, merge e rebase só com pedido explícito do usuário.
- Não edite arquivos gerados: `AGENTS.md`, `CLAUDE.md`, `.opencode/`, `.claude/`, `.agents/`, `.codex/`.

## Agentes

| Agente | Executa | Não executa |
| --- | --- | --- |
| `controller-hardware` | Define semântica de medição, protocolo de captura, fórmulas, unidades, janelas, critérios de aceite e thresholds; revisa os números; assina a revisão de hardware. | Não implementa código de produção, não edita `src/`, `tests/` ou CLI, não altera prompts/skills e não aprova decisão de produto. |
| `python-engineer` | Implementa domínio, aplicação, CLI, testes, persistência do relatório, documentação técnica e ADR. | Não define semântica de hardware nem thresholds; não altera `ai/` sem `prompt-engineer`; não altera o runtime `run`. |
| `prompt-engineer` | Atua somente se houver mudança em `ai/` (skills, instruções, prompts) e na revisão de consistência entre prompt, README e fontes. | Não implementa métricas, fórmulas, testes ou CLI; não assina critério de hardware. |
| Claude principal | Orquestra as etapas, faz handoffs com contexto, resolve conflitos, garante a ordem design → implementação → revisão e sintetiza o relatório final. | Não substitui o parecer de `controller-hardware`; não inventa threshold nem decide sozinho mudança de schema. |

Aprovação humana (usuário): aprova a spec antes da implementação, fornece captura real quando disponível e autoriza push/PR/merge.

Handoff mínimo entre agentes: objetivo, contexto, restrições, arquivos relevantes, saída esperada e critério de aceite. Em Claude Code, use a ferramenta **Agent** com o nome do subagente. Em Codex, use subagente ou siga o `FLOW.md` correspondente.

## Etapas e responsáveis

| # | Etapa | Executor | Revisor/apoio | Fluxo/skill | Saída | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Preflight, branch e baseline | `python-engineer` | Claude principal | `/flow-implement-feature` (passos 1–2) | branch `feat/calibration-metrics`, baseline pytest | tree limpo; 3.15.0; pytest verde |
| 2 | Spec de métricas e protocolo | `controller-hardware` | `python-engineer` | `/flow-design-feature` + `calibration-metrics`, `calibration-domain` | `docs/specs/metrics-v1.md` | unidades, janelas, fórmulas, mínimos de amostra e critérios aprovados pelo usuário |
| 3 | Decisão de schema e formato do relatório | `controller-hardware` + `python-engineer` | `prompt-engineer` | `/flow-design-feature` | ADR (próximo número livre, hoje `0004`) | perfil v1 intacto; relatório com versão própria; migração explicitada se houver v2 |
| 4 | Domínio de métricas | `python-engineer` | `controller-hardware` (fórmulas) | `/flow-implement-feature` (passo 3) + `calibration-metrics` | `src/zonepad/domain/metrics.py` + testes | domínio puro, sem IO; testes de caso conhecido verdes |
| 5 | Captura e manifesto de segmentos | `python-engineer` | `controller-hardware` | `/flow-implement-feature` (passo 5) | modelo de segmentos + loader validado | JSONL atual continua legível; manifesto inválido falha com mensagem acionável |
| 6 | Profile builder a partir de métricas | `python-engineer` | `controller-hardware` | `/flow-implement-feature` (passo 4) + `calibration-domain` | `build_profile_from_metrics` | perfil gerado passa em `validate_profile`; determinístico com relógio/UUID injetados |
| 7 | CLI `zonepad measure` e relatórios | `python-engineer` | Claude principal | `/flow-implement-feature` (passo 6) | subcomando + JSON + Markdown | `--help` completo; sem lógica de calibração na CLI; exit codes corretos |
| 8 | Testes sintéticos e replay | `python-engineer` | `controller-hardware` (semântica dos fixtures) | `python-quality` | suíte nova em `tests/` | casos felizes, bordas e erros; nenhum hardware |
| 9 | Smoke com captura real (se houver) | `controller-hardware` conduz; `python-engineer` apoia | Claude principal | `/flow-implement-feature` (passo 7) | relatório + parecer | números plausíveis; thresholds assinados; ausência declarada se não executado |
| 10 | README, ADR e `ai/` | `python-engineer` | `prompt-engineer` | `python-quality`, `prompt-design` | docs atualizadas | comandos copiáveis; `sync --check` limpo se `ai/` mudou |
| 11 | Revisão final | `controller-hardware`, `python-engineer`, `prompt-engineer` | Claude principal sintetiza | `/flow-review-calibration` | relatório de revisão | nenhum bloqueador; recomendações priorizadas com arquivo:linha |
| 12 | Encerramento | Claude principal | usuário | — | entrega no formato de saída | critérios de aceite marcados; riscos e handoff registrados |

`controller-hardware` é obrigatório nas etapas 2, 3, 4 (revisão), 6 (revisão), 9 e 11. Sem esse parecer, o incremento não está pronto.

## Decisões que a spec deve fechar

A spec da etapa 2 pode alterar estas propostas, mas cada mudança precisa de justificativa e dono. `controller-hardware` decide semântica; `python-engineer` decide estrutura de código.

| ID | Decisão | Recomendação inicial | Dono |
| --- | --- | --- | --- |
| D1 | Segmentação da captura | Manifesto sidecar (`captura.manifest.json`) com intervalos por `timestamp_ns`; JSONL permanece inalterado | `controller-hardware` |
| D2 | Camada das métricas | Normalizado (`[-1, 1]` sticks, `[0, 1]` triggers) como padrão; raw apenas como diagnóstico rotulado `*_raw` | `controller-hardware` |
| D3 | Onde mora o cálculo | Domínio puro em `domain/metrics.py`; orquestração em `application/measure.py`; IO em infraestrutura/CLI | `python-engineer` |
| D4 | Persistência de métricas | Relatório separado; perfil `schema_version=1` inalterado | `controller-hardware` + `python-engineer` |
| D5 | Deadzone sugerida | `max(raio_de_ruido_p99 * fator, piso)`, radial, modo `cut`; fator e piso explícitos e configuráveis | `controller-hardware` |
| D6 | Mínimos de amostra | Mínimos por segmento e por volta; capture insuficiente gera achado de qualidade, não exceção silenciosa | `controller-hardware` |
| D7 | Nome do comando | `zonepad measure` (verbo distinto de `replay` e `run`) | `python-engineer` |
| D8 | Taxa efetiva | `1 / mean(Δt)` com p5/p95; rejeitar timestamps não monotônicos | `controller-hardware` |
| D9 | Determinismo de teste | Relógio e fábrica de `profile_id` injetáveis; nenhuma dependência de `datetime.now()` no cálculo | `python-engineer` |
| D10 | Curva e inversão | Perfil gerado usa curva `linear` e `invert=false`; não inferir não linearidade neste incremento | `controller-hardware` |

## Decisão de schema

**Recomendação padrão:** manter `schema_version=1` no perfil e versionar o relatório separadamente com `metrics_schema_version=1` e `report_kind="calibration-metrics"`.

Consequências:

- Nenhum campo novo entra em `CalibrationProfile`; o validador continua rejeitando campos desconhecidos.
- O relatório é um artefato próprio, com validação estrita e sem reutilizar o schema do perfil.
- `build_profile_from_metrics` grava apenas o que o perfil já suporta: centro, ranges, deadzone, curva, inversão, repouso/fundo de trigger e `notes`.

**Se o design concluir que métricas precisam ser persistidas no perfil**, pare antes de codificar e exija:

1. ADR aprovado.
2. `schema_version=2` com validação estrita.
3. Migração v1 → v2 e teste de compatibilidade de leitura.
4. Atualização do README e dos prompts seguintes.

Não implemente schema v2 parcialmente nem aceite campos extras “tolerados”.

## Escopo

### 1. Domínio de métricas (`domain/metrics.py`)

Funções puras, tipos imutáveis (`frozen dataclass` com `slots=True`) e nenhuma importação de `pathlib`, SO, CLI ou bibliotecas de dispositivo.

Sticks, normalizado:

| Métrica | Definição | Unidade |
| --- | --- | --- |
| `center` | Mediana por eixo no repouso | `[-1, 1]` |
| `drift` | `max_t \|\|p(t) - c\|\|` no repouso | `[-1, 1]` (distância) |
| `noise_rms` | `sqrt(mean_t \|\|p(t) - c\|\|²)` por eixo e em 2D | `[-1, 1]` |
| `noise_p2p` | `max - min` por eixo | `[-1, 1]` |
| `noise_radius` | `max_t \|\|p(t) - c\|\|` e p99 | `[-1, 1]` |
| `range` | `max - min` por eixo, com `min`/`max` medidos | `[-1, 1]` |
| `symmetry` | `(max - c) / (c - min)` | adimensional |
| `deadzone_suggested` | `max(noise_radius * fator, piso)` | `[-1, 1]` radial |
| `circularity` | `min(r) / max(r)` no segmento de círculo | adimensional |
| `mean_radius` | `mean(r)` no círculo | `[-1, 1]` |
| `jitter` | `mean(\|Δp\|)` e `max(\|Δp\|)` entre amostras vizinhas | `[-1, 1]` |

Triggers, normalizado:

| Métrica | Definição | Unidade |
| --- | --- | --- |
| `rest` | Mediana no repouso | `[0, 1]` |
| `max` | Mediana dos máximos por ciclo | `[0, 1]` |
| `span` | `max - rest` | `[0, 1]` |
| `noise_rms`, `noise_p2p` | Ruído no repouso do trigger, por amostra | `[0, 1]` |
| `linearity_r2` | `R²` contra a reta repouso→fundo | adimensional |
| `linearity_max_error` | `max \|y - ŷ\|` | `[0, 1]` |
| `hysteresis` | `max \|y_subida(x) - y_descida(x)\|` | `[0, 1]` |
| `deadzone_suggested` | Piso de ruído no repouso, respeitando `rest < max` | `[0, 1]` |

Captura:

| Métrica | Definição | Unidade |
| --- | --- | --- |
| `effective_rate_hz` | `1 / mean(Δt)` | Hz |
| `rate_p5_hz`, `rate_p95_hz` | Dispersão da taxa | Hz |
| `duration_s` | `último timestamp - primeiro` | s |
| `saturation_ratio` | Proporção de amostras no extremo | `[0, 1]` |

Regras:

- Toda métrica expõe camada e unidade no modelo ou na documentação; não misture raw e normalizado.
- `p99` e pior caso entram no relatório, não apenas a média.
- Divisão por zero, série vazia, eixo ausente e valor não finito geram achado explícito, nunca `NaN`.
- Números não finitos são rejeitados na entrada e na serialização (`json.dumps(..., allow_nan=False)`).

Thresholds iniciais da skill `calibration-metrics` (drift < 0,02; ruído RMS < 0,005; circularidade > 0,90; R² > 0,98; histerese < 0,03; taxa ±10%). São defaults configuráveis, não universais; `controller-hardware` assina a versão efetiva e o relatório registra os valores usados.

### 2. Protocolo de captura e entrada

Formalize o protocolo de `ai/skills/calibration-metrics/SKILL.md` na spec: aquecimento, repouso, círculos horário/anti-horário, varreduras de trigger, repetições e preservação do raw.

Formato de entrada:

- JSONL existente, sem alteração obrigatória de schema: `device_id`, `timestamp_ns`, `axes`, `triggers`, `buttons`.
- Manifesto sidecar validado com `manifest_version=1`, identidade do dispositivo, arquivo de captura e segmentos:

```json
{
  "manifest_version": 1,
  "device": {"name": "Xbox Wireless Controller", "vid": "0x045e", "pid": "0x0b13"},
  "capture_file": "captura.jsonl",
  "segments": [
    {"kind": "rest", "start_ns": 2000000000, "end_ns": 7000000000, "warmup_ns": 1000000000},
    {"kind": "circle", "stick": "left", "direction": "cw", "start_ns": 7000000000, "end_ns": 9000000000},
    {"kind": "trigger_sweep", "trigger": "left", "start_ns": 12000000000, "end_ns": 22000000000}
  ]
}
```

Validações mínimas do manifesto: versão suportada, tipos corretos, `start_ns < end_ns`, intervalos não sobrepostos, segmentos dentro da captura, `kind` conhecido, dispositivo coerente com os frames e campos desconhecidos rejeitados. Sem manifesto, `measure` falha com mensagem acionável; não infira segmentos por heurística.

### 3. Profile builder

- Adicione `build_profile_from_metrics(device, metrics, *, app_version: str, now: Callable[[], datetime], profile_id_factory: Callable[[], str]) -> CalibrationProfile` em `application/calibration.py` ou módulo equivalente. `metrics` é o agregado imutável produzido pelo domínio.
- Preserve `build_profile` como wrapper compatível que calcula métricas e delega, ou marque a substituição com justificativa; não quebre chamadas existentes sem teste.
- Derive centro do repouso medido, ranges dos extremos medidos (clampados em `[-1, 1]`), deadzone da métrica sugerida com clamp em `[0, 0.95]` e triggers de `rest`/`max` medidos com `rest < max`.
- Garanta as invariantes de `StickCalibration`: `range_min < center < range_max`. Se a medição não permitir, falhe com erro acionável; não invente epsilon silencioso.
- Use curva `linear` e `invert=false` (D10).
- Registre em `notes` (≤ 2000 caracteres) a origem: arquivo de captura, versão do relatório e avisos de qualidade relevantes.
- Inclua o perfil gerado no relatório apenas como resumo; o perfil completo vai para o `ProfileStore` quando `--save-profile` for usado.

### 4. CLI `zonepad measure`

Aditiva; não altere o comportamento de `list`, `replay`, `profiles` ou `run`.

```bash
zonepad measure CAPTURE.jsonl \
  --manifest MANIFEST.json \
  [--report REPORT.json] \
  [--report-md REPORT.md] \
  [--save-profile DIR] \
  [--thresholds THRESHOLDS.json] \
  [--strict]
```

`--manifest` é obrigatório neste incremento: sem segmentos declarados, a medição não é reprodutível.

Comportamento:

1. Carregar e validar captura e manifesto.
2. Segmentar frames e calcular métricas.
3. Montar relatório e achados de qualidade.
4. Escrever JSON e/ou Markdown; sem caminho, imprimir o JSON em stdout.
5. Gerar e salvar perfil apenas com `--save-profile`; imprimir o `profile_id`.
6. `--strict` transforma achado de qualidade em falha (exit 4); sem `--strict`, avisos não bloqueiam.
7. Nenhuma leitura de `/dev/input` ou `/dev/uinput`; o comando é seguro na CI.

Exit codes:

| Código | Situação |
| --- | --- |
| `0` | relatório gerado; avisos podem existir sem `--strict` |
| `2` | captura, manifesto, thresholds ou argumentos inválidos |
| `4` | qualidade insuficiente com `--strict` |
| `1` | falha inesperada com mensagem acionável |

Mensagens de erro em PT-BR, sem stack trace, indicando arquivo e linha quando aplicável.

### 5. Relatório

JSON com validação estrita, `allow_nan=False` e campos em inglês:

```json
{
  "report_kind": "calibration-metrics",
  "metrics_schema_version": 1,
  "app_version": "0.1.0",
  "created_at": "2026-10-24T00:00:00Z",
  "device": {"name": "...", "vid": "0x045e", "pid": "0x0b13"},
  "capture": {
    "file": "captura.jsonl",
    "frames": 0,
    "duration_s": 0.0,
    "effective_rate_hz": 0.0,
    "rate_p5_hz": 0.0,
    "rate_p95_hz": 0.0
  },
  "protocol": {"segments": []},
  "sticks": {"left": {}, "right": {}},
  "triggers": {"left": {}, "right": {}},
  "quality": {"status": "pass", "findings": []},
  "thresholds": {},
  "notes": ""
}
```

Achados de qualidade usam códigos estáveis e testáveis, por exemplo: `REST_TOO_SHORT`, `MISSING_REST_SEGMENT`, `MISSING_CIRCLE_SEGMENT`, `MISSING_TRIGGER_SEGMENT`, `NON_MONOTONIC_TIME`, `DUPLICATE_TIMESTAMP`, `AXIS_MISSING`, `DEGENERATE_RANGE`, `CENTER_OUTSIDE_RANGE`, `LOW_CIRCULARITY`, `HIGH_DRIFT`, `HIGH_NOISE`, `LOW_TRIGGER_R2`, `HIGH_HYSTERESIS`, `RATE_OUT_OF_TOLERANCE`, `SATURATION_HIGH`, `INSUFFICIENT_CIRCLE_POINTS`.

Cada achado tem `code`, `severity` (`info`/`warning`/`error`), `message`, `metric` e `value` quando aplicável. `quality.status` é `pass`, `warn` ou `fail`, derivado dos achados.

Markdown segue a estrutura da skill `calibration-metrics` (dispositivo, captura, sticks, triggers, riscos). JSON é a fonte de verdade; Markdown não recalcula nada.

## Fora de escopo

- Wizard interativo e prompts passo a passo (prompt 03).
- GUI e PySide6 (prompt 05).
- Descoberta, filtragem por VID/PID/capabilities, hot-plug e mapeamento automático (prompt 04).
- Alterar `zonepad run`, `replay`, `profiles` ou `list`, exceto registrar o novo verbo no parser.
- Alterar o schema do perfil sem ADR, migração e teste de compatibilidade.
- Inferir curva, inversão, deadzone de firmware ou correção de gate não circular.
- Suporte a Windows/macOS, emulação, firmware ou kernel.
- Telemetria, nuvem ou envio de capturas.

## Critérios de aceite

- [ ] Spec de métricas aprovada pelo usuário, com unidades, janelas, fórmulas, protocolo e mínimos de amostra.
- [ ] ADR registra a decisão de schema e o formato do relatório, ou justifica a ausência.
- [ ] `domain/metrics.py` calcula todas as métricas da seção 1, sem IO e sem imports proibidos.
- [ ] Centro usa mediana; o relatório inclui pior caso e dispersão (p95/p99).
- [ ] Valores não finitos, séries vazias, eixos ausentes e divisão por zero são tratados com achado explícito.
- [ ] Manifesto de segmentos é validado e rejeita sobreposição, fora de ordem, tipo desconhecido e campo extra.
- [ ] `zonepad measure --help` documenta todos os argumentos, `--manifest` obrigatório e os exit codes.
- [ ] Relatório JSON e Markdown são gerados e consistentes entre si.
- [ ] `--strict` retorna 4 quando há achado bloqueante; sem ele, retorna 0 com avisos.
- [ ] `--save-profile` grava perfil que passa em `validate_profile` e pode ser carregado pelo `JsonProfileStore`.
- [ ] `build_profile_from_metrics` é determinístico com relógio e `profile_id` injetados.
- [ ] Perfil gerado mantém `range_min < center < range_max` e `rest < max`.
- [ ] Nenhum campo novo no perfil; `schema_version` permanece `1`.
- [ ] `zonepad run` e os demais subcomandos mantêm comportamento e testes atuais.
- [ ] Nenhum teste acessa `/dev/input`, `/dev/uinput` ou depende de hardware/sleep real.
- [ ] README documenta captura, manifesto, `measure`, relatório, thresholds e limitações.
- [ ] `python scripts/sync_ai_assets.py --check` limpo se `ai/` foi alterado.

## Testes obrigatórios

Use `pytest`, `tmp_path`, relógio fixo e fixtures sintéticas geradas em código ou `tests/fixtures/`.

| Caso | Entrada | Esperado |
| --- | --- | --- |
| Centro e drift | repouso constante em `(0.1, -0.1)` | `center` ≈ `(0.1, -0.1)`, `drift` = 0 |
| Ruído | repouso com `x` alternando `±0.01` e `y` fixo em 0 | `noise_rms` 2D ≈ `0.01`, `noise_p2p` em `x` = `0.02` |
| Deadzone | ruído com raio conhecido | `deadzone_suggested` = `max(raio * fator, piso)` |
| Circularidade | 1000 pontos de raio 0.9 | `circularity` ≈ 1; `mean_radius` ≈ 0.9 |
| Gate elíptico | raios 0.9 e 0.45 | `circularity` ≈ 0.5 |
| Linearidade | rampa linear 0→1 | `R²` ≈ 1; erro máximo ≈ 0 |
| Histerese | subida e descida com offset 0.05 | `hysteresis` ≈ 0.05 |
| Taxa | timestamps a 1 kHz | `effective_rate_hz` ≈ 1000 |
| Timestamp inválido | ordem decrescente ou duplicado | achado/erro com linha, sem exceção crua |
| Segmento curto | repouso abaixo do mínimo | achado `REST_TOO_SHORT`; perfil não é salvo em `--strict` |
| Captura vazia | arquivo vazio | exit 2 com mensagem acionável |
| Não finito | `NaN`/`Infinity` no JSONL | exit 2; serialização nunca emite `NaN` |
| Perfil | métricas sintéticas | `validate_profile` aprova; invariantes mantidas |
| Determinismo | mesma captura, relógio/UUID fixos | relatório e perfil idênticos |
| CLI | `--help`, stdout, arquivos, exit codes | conforme seção 4 |
| Compatibilidade | testes atuais de runtime e store | inalterados e verdes |

Adicione um teste de regressão que carregue uma captura real anonimizada em `tests/fixtures/` apenas se ela não contiver dados pessoais; caso contrário, use captura sintética.

## Validação

Execute e reporte a saída:

```bash
python --version
python -m pytest -q
ruff check .
ruff format --check .
mypy src/zonepad
python scripts/sync_ai_assets.py --check
zonepad measure --help
```

Se `ruff format --check` já falhar em `main` em arquivo fora do escopo, registre o débito e não o amplie. Se alguma ferramenta não estiver disponível, declare exatamente o que não foi executado.

Smoke opcional com captura real:

```bash
zonepad measure captura.jsonl --manifest captura.manifest.json \
  --report metricas.json --report-md metricas.md
```

Não execute `sudo`, não altere permissões e não acesse hardware sem confirmação.

## Documentação

- `docs/specs/metrics-v1.md`: problema, unidades, fórmulas, protocolo, mínimos, thresholds e decisões D1–D10.
- `docs/adr/0004-*.md`: decisão de schema e relatório separado (confirme o próximo número livre na execução).
- `README.md`: seção de medição, exemplo de manifesto, saída JSON/Markdown, thresholds e limitações.
- `ai/prompts/README.md`: status do prompt 02 (executado) após a conclusão — responsabilidade de `prompt-engineer`.
- Se `ai/` mudar, edite a fonte e rode `python scripts/sync_ai_assets.py` + `--check`; nunca edite espelhos.

## Riscos

| Risco | Impacto | Mitigação |
| --- | --- | --- |
| Amostra curta ou janela inadequada | deadzone e ruído irreais | mínimos por segmento, achados de qualidade, `--strict` |
| Variabilidade de hardware, temperatura e conexão | métricas não reprodutíveis | repetir sessão, reportar dispersão e pior caso, registrar conexão |
| Thresholds tratados como universais | falso aprovado/reprovado | defaults explícitos, configuráveis e assinados por `controller-hardware` |
| Segmentação manual errada | métricas calculadas sobre janela errada | validação do manifesto, cobertura e sobreposição |
| Deriva de schema entre perfil e relatório | incompatibilidade silenciosa | versões separadas, parsing estrito, ADR |
| Mapping manual ainda necessário no `run` | perfil medido não basta para executar | documentar que `measure` não substitui `--mapping` (prompt 04) |
| Não determinismo em testes | flakiness | relógio e `profile_id` injetados; fixtures fixas |
| Relatório grande ou ruidoso | baixo valor operacional | agregados + pior caso; Markdown enxuto; JSON como fonte |

## Formato de saída

Responda em PT-BR com:

1. **Plano executado** — 3–6 bullets, com a ordem real das etapas.
2. **Spec e decisões** — caminho da spec/ADR e decisões D1–D10 fechadas.
3. **Mudanças por arquivo** — contratos, assinaturas e schema do relatório.
4. **Métricas e unidades** — tabela do que foi implementado, com camada e unidade.
5. **Testes e validações** — comandos, resultados e o que não foi executado.
6. **Smoke com hardware** — o que foi medido, com qual dispositivo, e o que ficou pendente.
7. **Riscos e limitações** — incluindo thresholds ainda não validados em amostra maior.
8. **Próximo passo** — prompt 03 (wizard) e handoffs necessários.

## Invocação

### Claude Code (prioritária)

```text
Use o prompt em @ai/prompts/02-calibration-metrics.md.
Leia o arquivo inteiro antes de agir e siga a tabela "Etapas e responsáveis" na ordem.
Comece com /flow-design-feature: não escreva código de produção antes de a spec ser aprovada.
Delegue a semântica de medição, o protocolo, as fórmulas, as unidades e os critérios a
controller-hardware; delegue a implementação, os testes e a documentação técnica a
python-engineer. Use prompt-engineer apenas se houver mudança em ai/.
Implemente com /flow-implement-feature e faça a revisão final com /flow-review-calibration.
Valide com os comandos da seção "Validação" e entregue o relatório no "Formato de saída".
```

Variação em uma linha, se o harness pedir texto curto:

```text
Siga @ai/prompts/02-calibration-metrics.md: /flow-design-feature com controller-hardware,
depois /flow-implement-feature com python-engineer e /flow-review-calibration no final.
```

### Codex (alternativa)

```text
Siga o prompt em ai/prompts/02-calibration-metrics.md.
Leia o arquivo inteiro e execute as etapas na ordem. Use $flow-design-feature para a spec,
$flow-implement-feature para o código e $flow-review-calibration para a revisão.
Delegue semântica a controller-hardware e implementação a python-engineer.
```

Se os fluxos não existirem no harness, siga `ai/flows/flow-design-feature/FLOW.md`, `ai/flows/flow-implement-feature/FLOW.md` e `ai/flows/flow-review-calibration/FLOW.md`, e registre o fallback.

## Sequência

- **Prompt 02 (este):** motor de medição, relatório e geração de perfil.
- **Prompt 03:** wizard CLI de calibração, consumindo `measure` e o protocolo definidos aqui.
- **Prompt 04:** descoberta e mapeamento por família de dispositivo.
- **Prompt 05:** GUI.
- **Prompt 06:** qualidade, cobertura e release.

Não antecipe o wizard neste incremento. Se a implementação precisar de uma decisão de UX que pertence ao prompt 03, registre a pendência e siga com a API mínima.
