# Prompt 03 — Wizard CLI de calibração

- **Status:** pronto para Claude Code (prioridade) e Codex (alternativa).
- **Incremento:** comando aditivo `zonepad calibrate`, com captura guiada, medição, retry por segmento e perfil `schema_version=1`.
- **Branch de implementação:** `feat/calibration-wizard`, criada a partir de `main` com este prompt mergeado.
- **Fluxos:** `/flow-design-feature` → `/flow-implement-feature` → `/flow-review-calibration`.
- **Agentes:** `controller-hardware` (protocolo, timing, qualidade), `python-engineer` (state machine, portas, captura, testes), `prompt-engineer` (apenas `ai/` e consistência) e Claude principal (orquestração).
- **Fora deste incremento:** descoberta/hot-plug e mapeamento automático (prompt 04), GUI (prompt 05), qualidade/release (prompt 06).

## Missão

Entregar uma experiência de terminal em que a pessoa calibra um controle sozinha:

```bash
zonepad calibrate --device event3 --mapping mapping.json
```

O wizard conduz aquecimento, repouso, círculos nos dois sticks e varreduras de trigger; grava uma captura JSONL com manifesto compatível com `zonepad measure`; executa o motor de medição do prompt 02; mostra `quality.status` e achados; oferece retry dos segmentos que falharam; e grava um perfil v1 apenas quando a qualidade permite.

O wizard **não recalcula métricas nem reimplementa qualidade**. Ele orquestra `execute_measure`, grava a captura e decide quando repetir. O motor, os thresholds e as fórmulas continuam em `docs/specs/metrics-v1.md` e no prompt 02.

## Resultado esperado

1. Subcomando `zonepad calibrate` registrado no parser, sem alterar `run`, `measure`, `list`, `replay` ou `profiles`.
2. State machine pura, sem `input()`, `print()` ou `sleep()` no núcleo, com portas injetadas.
3. Console/prompter, relógio, sessão de captura, store e runner de medição atrás de `Protocol`.
4. Captura JSONL + manifesto gerados pelo wizard e aceitos por `zonepad measure` sem edição manual.
5. Política de retry por segmento com critérios explícitos, limite de tentativas e aborto sem perfil.
6. Perfil v1 persistido via `JsonProfileStore` e `build_profile_from_metrics`.
7. Ctrl+C e cancelamento com cleanup, sem perfil parcial e com caminhos informados.
8. Testes determinísticos com console roteirizado, sessão fake e relógio injetado; nenhum hardware na CI.

## Contexto verificado (2026-10-25)

Revalide no checkout principal, com working tree limpo. Os gates da seção **Validação** são a fonte de verdade.

| Verificação | Resultado |
| --- | --- |
| `main` | HEAD `9a02c8f`; PR #5 mergeou o motor de métricas do prompt 02 |
| CLI | `src/zonepad/interface/cli.py:56-107` registra `list`, `replay`, `profiles`, `run` e `measure`; não existe `calibrate` |
| Medição | `src/zonepad/application/measure.py:306` expõe `execute_measure`; `:380` expõe `save_profile`; `MeasureOptions(strict, save_profile)`; a CLI `measure` exige `--manifest` e `--mapping` |
| Perfil e store | `src/zonepad/application/calibration.py:170` `build_profile_from_metrics`; `infrastructure/json_profile_store.py:11` `JsonProfileStore` com gravação atômica; `schema_version=1` |
| Captura | `src/zonepad/infrastructure/capture_reader.py:87` `read_strict_capture`; campos permitidos: `device_id`, `timestamp_ns`, `axes`, `triggers`, `buttons` (`:19-20`) |
| Manifesto | `src/zonepad/infrastructure/manifest_reader.py:207`; `capture_file` deve ser o basename da captura; segmentos usam o mesmo `timestamp_ns` dos frames |
| Dispositivo | `src/zonepad/application/ports.py:11-30` `DeviceSession.read`, `DeviceBackend.list_devices`; `infrastructure/evdev.py:31` carimba `time.monotonic_ns()` no `SYN_REPORT` |
| Escrita de captura | inexistente; há apenas leitores de captura e manifesto |
| Protocolo | defaults em `src/zonepad/domain/metrics.py:67-85`: repouso mínimo 3 s/150 frames, 2 voltas válidas por direção, 3 ciclos válidos de trigger |
| Testes | `tests/` usa `pytest`, fakes, `tmp_path` e relógio fixo; nenhum hardware |

Leia antes de editar: `AGENTS.md`, `docs/specs/metrics-v1.md`, `docs/adr/0003-*.md`, `docs/adr/0004-*.md`, `src/zonepad/application/measure.py`, `src/zonepad/application/ports.py`, `src/zonepad/interface/cli.py`, `src/zonepad/infrastructure/manifest_reader.py`, `src/zonepad/infrastructure/capture_reader.py`, `src/zonepad/infrastructure/json_profile_store.py`, `src/zonepad/infrastructure/evdev.py` e `tests/`.

## Pré-condições

1. Este prompt deve estar mergeado em `main`. Enquanto não estiver, execute no checkout principal a partir da branch que contém o prompt e registre a exceção no relatório.
2. No checkout principal, crie a branch de implementação a partir da `main`:

```bash
cd /home/costa/Workspace/zonepad
git status --porcelain        # deve estar vazio
git switch main
git pull --ff-only
git switch -c feat/calibration-wizard
```

3. Toolchain, ambiente e baseline:

```bash
asdf current python        # deve mostrar 3.15.0; se não, pare e reporte
python --version           # Python 3.15.0
python -m venv .venv       # ou: virtualenv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q        # baseline verde antes de editar
```

4. Gates de entrada:

```bash
git status --porcelain        # vazio
git branch --show-current     # feat/calibration-wizard
git log --oneline main..HEAD  # vazio no início
```

Se qualquer gate falhar, pare e peça um checkout principal limpo.

5. Regras de segurança e git:

- Trabalhe no checkout principal; não use `git worktree` e não edite arquivos gerados (`AGENTS.md`, `CLAUDE.md`, `.opencode/`, `.claude/`, `.agents/`, `.codex/`).
- Não use `git stash`, `git reset`, `git checkout --`, `git restore`, `git rebase`, `git push --force` nem `sudo`.
- Commit local é permitido; push, PR, merge e rebase só com pedido explícito do usuário.
- Não acesse hardware real sem confirmação; a CI e os testes usam fakes.

## Agentes

| Agente | Executa | Não executa |
| --- | --- | --- |
| `controller-hardware` | Define o protocolo de captura do wizard (ordem, durações, instruções ao usuário, aquecimento, repetições), a semântica de timing e os critérios de retry/qualidade; revisa os números do smoke e assina o parecer de hardware. | Não implementa código de produção; não edita `src/`, `tests/` ou CLI; não altera prompts/skills; não decide UX de terminal sozinho. |
| `python-engineer` | Implementa a state machine, as portas, a sessão de captura, o adapter de console, a CLI `calibrate`, a integração com `execute_measure`, a persistência, os testes e a documentação técnica. | Não define durações, timing, thresholds nem semântica de qualidade; não altera fórmulas de métricas; não muda o schema do perfil; não altera o runtime `run`. |
| `prompt-engineer` | Atua apenas se a mudança tocar `ai/` (skills, instruções, prompts) e na revisão de consistência entre prompt, README e fontes. | Não implementa o wizard, a state machine, a captura ou os testes; não assina critério de hardware nem de UX. |
| Claude principal | Orquestra a ordem design → implementação → revisão, faz handoffs com contexto, resolve conflitos, cobra gates e sintetiza o relatório final. | Não substitui o parecer de `controller-hardware`; não inventa duração, threshold ou política de retry; não autoriza push/PR/merge. |

Aprovação humana (usuário): aprova a spec de UX/protocolo antes da implementação, executa o smoke com hardware quando possível e autoriza push/PR/merge.

Handoff mínimo: objetivo, contexto, restrições, arquivos relevantes, saída esperada e critério de aceite. Em Claude Code, use a ferramenta **Agent** com o nome do subagente. Em Codex, use subagente ou siga o `FLOW.md` correspondente.

## Etapas e responsáveis

| # | Etapa | Executor | Revisor/apoio | Fluxo/skill | Saída | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Preflight, branch e baseline | `python-engineer` | Claude principal | `/flow-implement-feature` (passos 1–2) | branch `feat/calibration-wizard`, baseline pytest | tree limpo; 3.15.0; pytest verde |
| 2 | Spec de UX de terminal, state machine, protocolo e retry | `controller-hardware` + `python-engineer` | Claude principal | `/flow-design-feature` + `calibration-metrics`, `calibration-domain`, `python-app-architecture` | `docs/specs/wizard-v1.md` | ordem, durações, instruções, retry e exit codes aprovados pelo usuário |
| 3 | Decisão de artefatos, nomes e contrato de CLI | `python-engineer` | `controller-hardware`, `prompt-engineer` | `/flow-design-feature` | ADR 0005 (próximo número livre) | layout, exit codes e compatibilidade com `measure` explícitos |
| 4 | Portas, state machine pura e adapters fake | `python-engineer` | `controller-hardware` (eventos de timing) | `/flow-implement-feature` (passos 4–5) + `clean-architecture` | `application/calibrate.py`, `application/ports.py`, fakes de teste | nenhum `input`/`print`/`sleep` no núcleo; reducer testável |
| 5 | Sessão de captura, writer JSONL e manifesto | `python-engineer` | `controller-hardware` (domínio de tempo) | `/flow-implement-feature` (passo 5) | `infrastructure/capture_writer.py` + testes | captura e manifesto aceitos por `read_strict_capture`/`load_manifest` |
| 6 | Console de terminal e seleção manual de dispositivo | `python-engineer` | Claude principal | `/flow-implement-feature` (passo 6) | `interface/terminal_console.py`, menu de dispositivos | TTY exigido; mensagens em PT-BR; sem descoberta automática |
| 7 | CLI `zonepad calibrate`, integração com medida, retry e cancelamento | `python-engineer` | `controller-hardware` (critérios de retry) | `/flow-implement-feature` (passos 4–6) + `clean-code` | subcomando + fluxo completo | `--help` completo; perfil só com qualidade aceita; Ctrl+C limpo |
| 8 | Testes de state machine, captura, retry e CLI | `python-engineer` | `controller-hardware` (fixtures) | `python-quality` | suíte nova em `tests/` | matriz da seção "Testes obrigatórios" verde; nenhum hardware |
| 9 | Smoke com hardware real (se houver) | `controller-hardware` conduz; `python-engineer` apoia | Claude principal | `/flow-implement-feature` (passo 7) | captura, relatório e parecer | movimento executável; números plausíveis; falhas declaradas |
| 10 | README, ADR e `ai/` | `python-engineer` (README/ADR) + `prompt-engineer` (`ai/`) | Claude principal | `python-quality`, `prompt-design` | docs e status do prompt 03 | comandos copiáveis; `sync --check` limpo se `ai/` mudou |
| 11 | Revisão final | `controller-hardware`, `python-engineer`, `prompt-engineer` | Claude principal sintetiza | `/flow-review-calibration` | relatório de revisão | nenhum bloqueador; recomendações com arquivo:linha |
| 12 | Encerramento | Claude principal | usuário | — | entrega no formato de saída | critérios marcados; riscos e handoff registrados |

`controller-hardware` é obrigatório nas etapas 2, 3 (revisão), 4 (timing), 7 (retry), 9 e 11. Sem esse parecer, o incremento não está pronto.

## Decisões que a spec deve fechar

A spec pode alterar estas propostas, mas cada mudança precisa de justificativa e dono. `controller-hardware` decide protocolo, timing e qualidade; `python-engineer` decide estrutura de código e artefatos.

| ID | Decisão | Recomendação inicial | Dono |
| --- | --- | --- | --- |
| D1 | UX de terminal | Texto simples em PT-BR, sem dependência nova, menus numerados, confirmação explícita e contagem regressiva; exigir TTY | `python-engineer` |
| D2 | Onde mora a state machine | Núcleo puro em `application/calibrate.py`; efeitos apenas por portas; CLI e terminal na borda | `python-engineer` |
| D3 | Ordem e durações dos segmentos | Aquecimento 2 s não declarado; repouso 5 s com `warmup_ns=1 s`; círculos 6 s por direção; triggers 12 s por lado; valores configuráveis | `controller-hardware` |
| D4 | Política de retry | Retry por segmento com máximo 2 repetições por alvo e teto global de 6; os intervalos afetados saem do manifesto, os novos entram e a captura inteira é re-medida | `controller-hardware` |
| D5 | Artefatos e nomes | Subdiretório por sessão em `~/.local/share/zonepad/captures/<UTC>-<device>/` com `capture.jsonl`, `capture.manifest.json`, `report.json`, `report.md` | `python-engineer` |
| D6 | Domínio de tempo da captura | Rebasear frames para começar em 0 ns e gravar os limites dos segmentos no mesmo domínio; um único relógio injetado | `controller-hardware` + `python-engineer` |
| D7 | Integração com a medição | Chamar `execute_measure` em processo com `strict=True` e `save_profile=True`; não usar subprocesso nem duplicar avaliação de qualidade | `python-engineer` |
| D8 | Persistência do perfil | `JsonProfileStore`; gravar relatório antes; salvar perfil só depois da aceitação; nunca perfil parcial | `python-engineer` |
| D9 | Cancelamento | Ctrl+C encerra a captura, preserva a captura parcial, não grava manifesto/report/perfil e retorna 130 | `python-engineer` |
| D10 | Testabilidade | Portas injetadas, console roteirizado, sessão fake com frames e relógio fixo; proibido hardware e `sleep` real nos testes | `python-engineer` |

## Escopo

### 1. CLI `zonepad calibrate`

```bash
zonepad calibrate \
  [--device event3] \
  --mapping mapping.json \
  [--capture-dir ~/.local/share/zonepad/captures] \
  [--profiles-dir ~/.config/zonepad/profiles] \
  [--thresholds thresholds.json] \
  [--warmup-seconds 2] \
  [--rest-seconds 5] \
  [--circle-seconds 6] \
  [--trigger-seconds 12] \
  [--max-retries 2]
```

Comportamento:

1. `--mapping` é obrigatório e deve definir `lx`, `ly`, `rx`, `ry`, `lt`, `rt`; faltando canal, saia com 2 e liste os canais ausentes antes de abrir o dispositivo.
2. `--device` é opcional. Sem ele, liste os dispositivos de `DeviceBackend.list_devices()` e peça a escolha por número. Seleção manual, sem filtro por VID/PID, sem hot-plug.
3. Valide durações positivas, thresholds e diretórios antes da captura; se os mínimos de `MetricsConfig.protocol` não couberem nas durações, ajuste ou falhe com exit 2; falha de escrita também encerra com mensagem acionável.
4. Exija TTY para o modo interativo; sem TTY, saia com 2 e explique que `calibrate` é interativo (`--help` funciona sem TTY).
5. Registre o subcomando sem alterar os existentes. Nenhuma lógica de métricas na CLI.

Exit codes:

| Código | Situação |
| --- | --- |
| `0` | perfil salvo, ou qualidade aceita e usuário recusou salvar (artefatos preservados) |
| `2` | argumentos, mapping, thresholds, manifesto ou captura inválidos |
| `3` | dispositivo indisponível, desconectado ou sem permissão |
| `4` | qualidade bloqueante após os retries; nenhum perfil salvo |
| `130` | Ctrl+C ou cancelamento do usuário |
| `1` | falha inesperada com mensagem acionável |

### 2. Camadas e portas

| Porta | Responsabilidade | Adapter |
| --- | --- | --- |
| `Console` | `say`, `ask_choice`, `ask_confirm`, `show_progress`, `show_findings` | `interface/terminal_console.py` (único lugar com `input()`/`print()`) |
| `Clock` | `now_ns()` monotônico e `sleep(seconds)` | `infrastructure/clock.py` (único lugar com `time.monotonic_ns`/`time.sleep`) |
| `CaptureSession` | abrir dispositivo, `record_segment(spec, progress) -> Segment`, `flush()`/`finish() -> CaptureArtifacts`, `abort()` | `infrastructure/capture_writer.py` + `DeviceSession` |
| `ProfileStore` | `load`/`save` do perfil | `JsonProfileStore` existente |
| `MeasureRunner` | montar `MeasureInputs` e chamar `execute_measure` | `infrastructure/measure_runner.py` (compõe `read_strict_capture` + `execute_measure`) |

Regras:

- `domain/` e `application/` não importam `input`, `print`, `time.sleep`, `time.monotonic_ns`, `os`, `pathlib` nem `evdev`; caminhos cruzam a fronteira como `str`.
- A state machine recebe as portas e devolve efeitos explícitos; não bloqueia em I/O além das chamadas de porta.
- O adapter de console traduz teclas e valida respostas; o núcleo recebe eventos tipados (`Confirm`, `Choose`, `Cancel`, `SegmentDone`).

### 3. State machine

Estados mínimos:

```text
WELCOME → SELECT_DEVICE → VALIDATE_MAPPING → CONFIRM_DEVICE → WARMUP → REST
        → CIRCLE(left, cw) → CIRCLE(left, ccw)
        → CIRCLE(right, cw) → CIRCLE(right, ccw)
        → TRIGGER(left) → TRIGGER(right)
        → MEASURE → REVIEW → [RETRY → SEGMENT_RETRY → MEASURE]* → SAVE → SUMMARY
```

Regras:

- `WELCOME` apresenta o objetivo, o protocolo e o tempo estimado; `CONFIRM_DEVICE` mostra nome, VID/PID, nó e caminho do mapping e exige confirmação antes de abrir a captura.
- `REVIEW` classifica o resultado em `pass`, `warn` ou `fail` a partir de `outcome.exit_reason`, `quality.status` e achados; não recalcula thresholds.
- `RETRY` só existe se houver achado elegível, tentativas disponíveis e o usuário aceitar.
- `SEGMENT_RETRY` retira do manifesto os intervalos afetados, grava os novos segmentos na ordem do protocolo e volta a `MEASURE`.
- `SAVE` emite o efeito de persistir uma única vez e a borda chama `save_profile`; `SUMMARY` informa caminhos e `profile_id` sem reimprimir o relatório.
- Cancelamento é um evento que leva a `ABORTED` de qualquer estado, com cleanup idempotente.
- Prefira um reducer puro `step(state, event) -> (state, effects)`; se usar classe, mantenha métodos sem I/O direto.

### 4. Protocolo de captura

O protocolo detalhado e as justificativas ficam em `docs/specs/wizard-v1.md`; as fórmulas e os mínimos ficam em `docs/specs/metrics-v1.md`. Não duplique fórmulas.

| # | Segmento | `kind` | Alvo | Duração padrão | Instrução ao usuário | Mínimo |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | Aquecimento | não declarado | — | 2 s | "Solte o controle e não toque nos sticks" | nenhum |
| 1 | Repouso | `rest` | ambos | 5 s (`warmup_ns=1 s`) | "Mãos fora do controle até o fim" | 3 s efetivos / 150 frames por canal |
| 2 | Círculo | `circle` | `left`, `cw` | 6 s | "Comece na borda e dê 3 voltas horárias, passando do ponto inicial" | 2 voltas válidas |
| 3 | Círculo | `circle` | `left`, `ccw` | 6 s | idem, anti-horário | 2 voltas válidas |
| 4 | Círculo | `circle` | `right`, `cw` | 6 s | idem, stick direito | 2 voltas válidas |
| 5 | Círculo | `circle` | `right`, `ccw` | 6 s | idem, anti-horário | 2 voltas válidas |
| 6 | Trigger | `trigger_sweep` | `left` | 12 s | "5 pressões lentas até o fundo, com pausa no repouso e no fundo" | 3 ciclos válidos |
| 7 | Trigger | `trigger_sweep` | `right` | 12 s | idem, gatilho direito | 3 ciclos válidos |

- Antes de cada segmento, mostre a instrução e aguarde Enter; em seguida, faça a contagem de 3 s, e os limites começam no fim da contagem.
- Frames durante instruções, pausas e contagem são gravados, mas ficam fora dos segmentos declarados; `measure` os ignora.
- A captura corre do início do aquecimento até o fim do último segmento; pausas não geram segmentos.
- Cada segmento começa e termina no relógio injetado, no mesmo domínio dos frames.
- Garanta `start_ns >= ts_first` e `end_ns <= ts_last + 1`; faça clamp contra o primeiro/último frame, derive o fim do último frame do segmento, descarte intervalo vazio e trate-o como falha de qualidade.
- A sessão lê com timeout curto e compara o deadline pelo `Clock`; o núcleo apenas aguarda o evento de fim.
- Desconexão durante um segmento aborta a sessão com exit 3 e cleanup; não tente reconectar.
- Exija todos os segmentos neste incremento: pular stick ou trigger produziria perfil incompleto. Para interromper, use cancelamento explícito.

### 5. Captura e manifesto

Layout padrão por sessão:

```text
~/.local/share/zonepad/captures/2026-10-25T14-30-00Z-event3/
├── capture.jsonl
├── capture.manifest.json
├── report.json
└── report.md
```

Regras do writer:

- Uma linha JSON por frame, apenas `device_id`, `timestamp_ns`, `axes`, `triggers`, `buttons`; `buttons` ordenado, `allow_nan=False`, UTF-8.
- `device_id` igual ao `DeviceInfo.device_id` em todas as linhas; `timestamp_ns` inteiro e monotônico, rebaseado para 0 ns no primeiro frame (D6), com os limites de segmento no mesmo deslocamento.
- `capture.manifest.json` com `manifest_version=1`, `device` (`vid`/`pid` em `0x%04x`), `capture_file` igual ao basename, `segments` ordenados e sem sobreposição; `capture_sha256` calculado após o flush.
- `flush()` grava uma captura consistente e o manifesto correspondente sem fechar a sessão; `finish()` fecha e grava a versão final.
- `abort()` antes do protocolo completo grava a captura parcial, remove manifesto/relatório já gravados, não grava perfil e retorna o caminho para o resumo.
- Verifique o limite de 32 MiB de `read_strict_capture` antes de exceder; avise e aborte com exit 2 se a captura chegar perto do limite.
- Sanitize o `device_id` no nome do diretório e não reutilize uma sessão existente: acrescente sufixo `-2`, `-3`, etc., de forma determinística com o relógio injetado.

### 6. Medição, qualidade e retry

- Use `execute_measure(inputs, MeasureOptions(strict=True, save_profile=True), ...)` com `app_version`, `now` e `profile_id_factory` injetados.
- Monte `MeasureInputs` com a captura recém-gravada (`read_strict_capture`), o manifesto, `mapping.axes`, `mapping.triggers`, `mapping_sha256` e `MetricsConfig` (defaults ou `--thresholds`).
- Trate o resultado assim:

| `exit_reason` | `quality.status` | Ação |
| --- | --- | --- |
| `ok` | `pass` | Mostrar resumo, pedir confirmação e salvar |
| `ok` | `warn` | Mostrar achados, pedir confirmação (padrão salvar) e salvar se aceito |
| `strict_blocked` | `fail` ou `warn` | Mapear achados bloqueantes para segmentos; retry se elegível; senão abortar com 4 |
| `profile_not_derivable` | qualquer | Abortar com 4, explicar o motivo e preservar relatório |

- Achados com `blocks_strict` orientam o retry; achados `info` e os não bloqueantes (`LOW_CIRCULARITY`, `SATURATION_HIGH`, `LOW_TRIGGER_R2`, `HIGH_HYSTERESIS`) são apenas exibidos.
- Retry elegível (proposta; `controller-hardware` assina): `REST_TOO_SHORT`, `HIGH_DRIFT`, `HIGH_NOISE` → novo `rest`; `INSUFFICIENT_CIRCLE_POINTS`, `INSUFFICIENT_CIRCLE_LAPS`, `CIRCLE_DIRECTION_INCONSISTENT` → novo círculo do stick/direção indicado; `INSUFFICIENT_TRIGGER_CYCLES` → nova varredura do trigger indicado.
- Sem retry: `MISSING_*`, `AXIS_MISSING`, `DEGENERATE_RANGE`, `CENTER_OUTSIDE_RANGE`, `MAPPING_RANGE_EXCEEDED`, `DUPLICATE_TIMESTAMP`, `RATE_OUT_OF_TOLERANCE`, `DEADZONE_CLAMPED` → exit 4; captura inválida (timestamp não monotônico) → exit 2; dispositivo → exit 3.
- Cada retry remove do manifesto o intervalo do segmento afetado e anexa um novo segmento; os frames antigos permanecem na captura, mas ficam fora de qualquer segmento. Refaça `flush()` e re-meça a captura inteira.
- Limite: `--max-retries` por alvo (padrão 2) e teto global de 6 retries. Esgotado o limite, mostre os achados e aborte sem perfil.
- Interprete o `metric` do achado para localizar o alvo; sem alvo seguro, aborte e registre a pendência.
- Exiba `quality.status`, cada achado com `severity`, `code`, `message` e `metric=value` quando houver, e o caminho do relatório.
- Grave o relatório com `dumps_report`/`render_markdown` e `write_text_atomic`; o JSON é a fonte de verdade.
- Nunca grave perfil quando `outcome.profile is None`; `save_profile` só é chamado com perfil derivado.

### 7. Persistência e resumo

- Salve o perfil apenas em `--profiles-dir` via `JsonProfileStore`, depois de gravar relatório JSON/Markdown.
- Garanta `schema_version=1`, `profile_id` UUID v4 e `validate_profile`; não adicione campos.
- Resumo final com: dispositivo, duração total, número de retries, `quality.status`, caminhos de captura/manifesto/relatórios, `profile_id` e próximo comando:

```bash
zonepad run --device event3 --profile <uuid> --mapping mapping.json
```

- Se o usuário recusar salvar, informe que os artefatos foram preservados e que nenhum perfil foi gravado; exit 0.

### 8. Cancelamento e cleanup

- Ctrl+C, `EOFError`, escolha "cancelar" e `KeyboardInterrupt` convergem para o mesmo caminho idempotente com exit 130.
- Encerre o loop, faça `flush()`/`close()` da captura e feche o dispositivo em `finally`.
- Protocolo incompleto: preserve `capture.jsonl`, não escreva manifesto, relatório nem perfil; informe o caminho e "captura incompleta".
- Protocolo completo sem aceite: preserve captura, manifesto e relatório; não grave perfil.
- Mensagens em PT-BR, sem stack trace; nenhum temporário do store permanece (`JsonProfileStore` grava atomicamente); exit 130 para cancelamento e 3 para desconexão.

## Fora de escopo

- Descoberta, filtros por VID/PID/capabilities, hot-plug e mapeamento automático (prompt 04).
- GUI e PySide6 (prompt 05).
- Qualidade, cobertura e release (prompt 06).
- Alterar fórmulas, thresholds, unidade ou semântica de métricas.
- Alterar `schema_version` do perfil ou criar schema v2.
- Alterar `zonepad run`, `measure`, `list`, `replay` ou `profiles`, exceto registrar `calibrate` no parser.
- Controles sem sticks completos ou sem triggers, e suporte a Windows/macOS, emulação, firmware ou kernel.
- Telemetria, nuvem ou envio de capturas.
- Push, PR, merge ou rebase.

## Critérios de aceite

- [ ] `zonepad calibrate --help` documenta todos os argumentos, o modo interativo e os exit codes.
- [ ] `calibrate` é aditivo; testes de `run`, `measure`, `list`, `replay` e `profiles` continuam verdes.
- [ ] `--device` omitido lista dispositivos e permite escolha manual; não há filtro automático nem hot-plug.
- [ ] Mapping sem `lx`, `ly`, `rx`, `ry`, `lt` ou `rt` falha com exit 2 antes de abrir o dispositivo.
- [ ] A captura gerada é aceita por `read_strict_capture` e o manifesto por `load_manifest` sem edição.
- [ ] Os limites dos segmentos estão no mesmo domínio de tempo dos frames e não se sobrepõem.
- [ ] `zonepad measure` executa sobre os artefatos do wizard e produz relatório coerente.
- [ ] A state machine não chama `input`, `print`, `sleep` nem lê o relógio diretamente.
- [ ] Console, relógio, sessão de captura, store e runner de medição são injetáveis.
- [ ] Caminho feliz grava perfil v1 que passa em `validate_profile` e pode ser carregado pelo store.
- [ ] `strict_blocked` aciona retry apenas para achados elegíveis e dentro do limite.
- [ ] Após esgotar retries, nenhum perfil é gravado e o exit code é 4.
- [ ] `warn` exibe achados e permite salvar; recusa preserva artefatos e não grava perfil.
- [ ] Ctrl+C durante a captura preserva a captura parcial, não grava manifesto/report/perfil e retorna 130.
- [ ] Desconexão do dispositivo retorna 3 com cleanup e sem perfil.
- [ ] Nenhum teste acessa `/dev/input`, `/dev/uinput` ou depende de hardware, TTY real ou `sleep` real.
- [ ] Nenhum perfil parcial ou temporário permanece após falha de escrita.
- [ ] O resumo final inclui caminhos, `profile_id` e o comando `zonepad run`.
- [ ] `docs/specs/wizard-v1.md` e ADR 0005 registram protocolo, state machine, retry, artefatos e exit codes.
- [ ] README documenta `calibrate`, requisitos de TTY e limitações.
- [ ] `python scripts/sync_ai_assets.py --check` limpo se `ai/` foi alterado.

## Testes obrigatórios

Use `pytest`, `tmp_path`, relógio fixo, console roteirizado e sessão fake que sintetiza frames na mesma linha do tempo do clock. Nenhum hardware.

| Caso | Entrada | Esperado |
| --- | --- | --- |
| Caminho feliz | console confirma tudo, frames sintéticos válidos | perfil v1 salvo; captura/manifesto/relatórios existem; exit 0 |
| Compatibilidade | artefatos do caminho feliz | `zonepad measure --manifest --mapping` lê a captura e gera relatório com os mesmos segmentos |
| Qualidade `warn` | achado não bloqueante | achados exibidos; confirmação; perfil salvo |
| Recusa em `warn` | usuário recusa | artefatos preservados; nenhum perfil; exit 0 |
| Retry com sucesso | primeira captura curta, retry regrava o segmento | intervalo antigo sai do manifesto; novo entra; segunda medição passa; perfil salvo |
| Retry esgotado | falha persiste após `--max-retries` | exit 4; nenhum perfil; relatório preservado |
| Achado não elegível | `MAPPING_RANGE_EXCEEDED` | sem retry; exit 4 com mensagem acionável |
| Perfil não derivável | métricas sem invariantes de perfil | exit 4; relatório preservado; nenhum perfil |
| Aborto do usuário | cancelar antes do primeiro segmento | sem manifesto/report/perfil; captura vazia pode existir; exit 130 |
| Ctrl+C no meio | interrupção durante círculo | `capture.jsonl` fechado; sem manifesto/report/perfil; exit 130 |
| Desconexão | sessão fake levanta `DeviceDisconnectedError` | exit 3; cleanup; sem perfil |
| Mapping ou thresholds inválidos | falta `lt`; campo desconhecido | exit 2 antes de abrir dispositivo; lista canais/campos ausentes |
| Sem TTY | console não interativo | exit 2 com orientação; `--help` continua funcionando |
| Dispositivo inválido | `--device event99` | exit 3; sem captura |
| Determinismo | relógio e UUID fixos, mesmo roteiro | mesmos nomes, mesmos limites de segmento e mesmo perfil |
| Bordas de tempo | primeiro frame depois do início do `rest` | manifesto válido com clamp; segmento vazio vira achado e retry |
| Store | perfil gerado | `JsonProfileStore.load` devolve perfil igual; `schema_version=1` |
| Regressão | comandos existentes | testes atuais inalterados e verdes |

Adicione um teste que verifique que a captura não contém campos extras e que `buttons` está ordenado. Se usar captura real anonimizada, confirme que não há dados pessoais.

## Validação

Execute e reporte a saída:

```bash
python --version
python -m pytest -q
ruff check .
ruff format --check .
mypy src/zonepad
python scripts/sync_ai_assets.py --check
zonepad calibrate --help
```

Smoke manual opcional, com dispositivo real e autorização explícita:

```bash
zonepad calibrate --device event3 --mapping mapping.json
zonepad measure <captura>/capture.jsonl --manifest <captura>/capture.manifest.json \
  --mapping mapping.json --report <captura>/recheck.json
```

Se `ruff format --check` já falhar em `main` em arquivo fora do escopo, registre o débito e não o amplie. Se alguma ferramenta não estiver disponível, declare exatamente o que não foi executado. Não execute `sudo`, não altere permissões e não acesse hardware sem confirmação.

## Documentação

- `docs/specs/wizard-v1.md`: problema, usuário, UX, state machine, protocolo, retry, artefatos, exit codes e decisões D1–D10.
- `docs/adr/0005-*.md`: contrato de `calibrate`, artefatos e política de retry; confirme o próximo número livre.
- `README.md`: seção de calibração guiada, requisitos de TTY, exemplo de sessão, artefatos, limitações e próximo `run`.
- `ai/prompts/README.md`: marcar o prompt 03 como concluído após a implementação — responsabilidade de `prompt-engineer`; se `ai/` mudar, rode `python scripts/sync_ai_assets.py` + `--check` e nunca edite espelhos.

## Riscos

| Risco | Impacto | Mitigação |
| --- | --- | --- |
| Timing impreciso entre contagem, relógio e frames | segmentos deslocados e métricas erradas | relógio único injetado; limites no mesmo domínio; teste de determinismo |
| UX confusa ou movimento irregular | usuário erra o gesto; voltas e ciclos inválidos | instruções curtas, contagem, exemplo de movimento, mínimos da spec e retry guiado |
| Retry remove o segmento errado | perda de dados bons e métricas piores | mapear pelo `metric`, confirmar o alvo e limitar tentativas; re-medir a captura inteira |
| Mapping manual errado | ranges e triggers irreais | validação de canais, `MAPPING_RANGE_EXCEEDED` e mensagem acionável |
| Captura grande | limite de 32 MiB e sessão lenta | guarda de tamanho; aviso e aborto antes do limite |
| Hardware ausente ou sem permissão | bloqueio de desenvolvimento | fakes na CI; smoke opcional; declaração explícita do que não foi validado |
| Ctrl+C em ponto inconsistente | captura corrompida | flush/close em `finally`; sem manifesto/report/perfil quando incompleta |
| Flakiness por tempo real | testes instáveis | relógio e sleeper injetados; nenhum `sleep` real |

## Formato de saída

Responda em PT-BR com:

1. **Plano executado** — 3–6 bullets com a ordem real das etapas.
2. **Spec e decisões** — caminho de `wizard-v1.md`, ADR 0005 e decisões D1–D10 fechadas.
3. **Mudanças por arquivo** — CLI, state machine, portas, writer, console, testes e docs.
4. **Contratos** — assinaturas das portas, estados, artefatos e exit codes.
5. **Testes e validações** — comandos, resultados e o que não foi executado.
6. **Smoke com hardware** — dispositivo, movimento executado, achados e pendências; declare se não foi feito.
7. **Riscos e limitações** — retry, timing, mapping manual e cobertura do protocolo.
8. **Próximo passo** — handoff para o prompt 04 e o que o wizard deixa como seam de descoberta.

## Invocação

### Claude Code (prioritária)

```text
Use o prompt em @ai/prompts/03-calibration-wizard.md.
Leia o arquivo inteiro antes de agir e siga a tabela "Etapas e responsáveis" na ordem.
Comece com /flow-design-feature: não escreva código de produção antes de a spec de UX,
state machine, protocolo e retry ser aprovada.
Delegue protocolo, timing, durações, critérios de retry e revisão dos números a
controller-hardware. Delegue state machine, portas, writer, CLI, testes e documentação
técnica a python-engineer. Use prompt-engineer apenas se houver mudança em ai/.
Implemente com /flow-implement-feature e faça a revisão final com /flow-review-calibration.
Valide com os comandos da seção "Validação" e entregue o relatório no "Formato de saída".
```

### Codex (alternativa)

```text
Siga o prompt em ai/prompts/03-calibration-wizard.md.
Leia o arquivo inteiro e execute as etapas na ordem. Use $flow-design-feature para a spec,
$flow-implement-feature para o código e $flow-review-calibration para a revisão.
Delegue protocolo, timing e retry a controller-hardware e implementação a python-engineer.
```

Se os fluxos não existirem no harness, siga `ai/flows/flow-design-feature/FLOW.md`, `ai/flows/flow-implement-feature/FLOW.md` e `ai/flows/flow-review-calibration/FLOW.md`, e registre o fallback.

## Sequência

- **Prompt 02 (concluído):** motor de medição, relatório e geração de perfil.
- **Prompt 03 (este):** wizard CLI de calibração, consumindo `measure` e o protocolo definidos no 02.
- **Prompt 04:** descoberta e mapeamento por família; substitui a seleção manual e o mapping manual.
- **Prompt 05:** GUI sobre o mesmo núcleo.
- **Prompt 06:** qualidade, cobertura e release.

Não antecipe descoberta, hot-plug, GUI ou schema v2. Se a implementação precisar de uma decisão do prompt 04, registre a pendência e mantenha a seleção manual atrás de uma porta.

## Handoff para o prompt 04

Entregue ao próximo incremento:

1. O seam de seleção (`DeviceBackend.list_devices` + escolha manual) e o ponto onde a descoberta automática entra.
2. O contrato do writer/manifesto, com as suposições de tempo, rebase e canais exigidos (`lx`, `ly`, `rx`, `ry`, `lt`, `rt`).
3. Os achados com retry, os que exigem correção de mapping e as pendências do smoke, com passos de reprodução.
