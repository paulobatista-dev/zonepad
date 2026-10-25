# Spec — Wizard CLI de calibração v1

- **Status:** aprovada pelo usuário em 2026-10-25; implementação concluída e em revisão.
- **Data:** 2026-10-25
- **Base:** `ai/prompts/03-calibration-wizard.md`, `docs/specs/metrics-v1.md`, ADRs 0003 e 0004.
- **Evidência:** decisões de hardware abaixo foram revisadas por `controller-hardware`; contratos de aplicação foram revisados por `python-engineer`. Nenhum hardware real foi acessado.

## Problema

`zonepad measure` mede capturas existentes, mas não guia a pessoa a produzir uma captura válida nem oferece repetição localizada de segmentos problemáticos. O wizard adicionará uma sessão interativa que grava captura e manifesto compatíveis com `measure`, chama o motor existente e salva perfil v1 somente quando a qualidade permitir.

## Usuário e contexto

Pessoa em Linux com controle compatível com backend evdev, mapping manual e terminal interativo. A execução seleciona manualmente um dispositivo, confirma sua identidade, orienta os movimentos e informa qualidade, achados e arquivos produzidos. `DeviceSession.read()` fornece frames raw; `execute_measure` aplica o mapping e calcula as métricas.

## Resultado esperado

`zonepad calibrate --device event3 --mapping mapping.json` conduz o protocolo, preserva artefatos rechecáveis por `zonepad measure`, oferece retry apenas para achados resolvíveis e grava um perfil schema v1 apenas após derivação válida e aceite do usuário.

## Escopo

- Novo subcomando aditivo `calibrate`, seleção manual por `DeviceBackend`, TTY obrigatório para execução interativa.
- State machine pura em `application/calibrate.py`, portas injetáveis e adapters nas bordas.
- Escrita de JSONL/manifesto, retries, runner para `execute_measure`, relatórios, persistência por `JsonProfileStore` e resumo final.
- Artefatos locais por sessão; captura raw permanece sem canais derivados.

## Fora de escopo

Descoberta/hot-plug, identificação automática, mapping automático, GUI, outras plataformas, firmware/kernel/emulação, fórmulas ou thresholds novos, schema de perfil v2 e alterações semânticas nos comandos existentes. Smoke com dispositivo real depende de autorização explícita.

## Requisitos funcionais

1. `--mapping` é obrigatório; validar os canais `lx`, `ly`, `rx`, `ry`, `lt`, `rt` e thresholds antes de abrir o dispositivo.
2. `--device` é opcional; sem ele, listar e permitir escolha manual. Mostrar dispositivo e mapping e obter confirmação antes de abrir a sessão.
3. A execução requer TTY. `--help` funciona sem TTY. O console do terminal é o único adapter que usa `input()`/`print()`.
4. Capturar continuamente a partir do aquecimento, incluindo pausas, instruções e contagens; somente janelas declaradas entram em métricas.
5. Chamar `execute_measure` em processo com `MeasureOptions(strict=True, save_profile=True)`; exibir status e achados retornados sem recalcular qualidade.
6. Para `exit_reason=ok` e status `pass` ou `warn`, mostrar o resultado e pedir confirmação de salvar (padrão afirmativo no caso `warn`). Recusa preserva captura, manifesto e relatórios e não salva perfil.
7. Para `strict_blocked`, oferecer retry somente se todos os achados bloqueantes relevantes puderem ser mapeados com segurança para alvos elegíveis. Regravar o segmento alvo, remover sua janela antiga do manifesto, conservar seus frames fora de segmentos e reexecutar a medição integral.
8. Para `profile_not_derivable`, mapping/entrada inválida, desconexão, cancelamento ou falha inesperada, nunca persistir perfil; preservar artefatos compatíveis com o estágio alcançado e informar caminho/motivo.
9. O relatório JSON e Markdown são gravados antes de persistir perfil. `save_profile` só recebe resultado com perfil derivado.
10. Resumo inclui dispositivo, duração, retries, status, caminhos, `profile_id` quando houver e comando seguinte `zonepad run --device <id> --profile <uuid> --mapping <arquivo>`.

## Requisitos não funcionais

- Domínio e aplicação sem I/O de terminal, filesystem, relógio de sistema ou hardware direto; efeitos via portas.
- Mesmo input e dependências fake/injetadas produzem estados, timestamps e nomes determinísticos.
- Testes usam relógio, console e sessão fake, sem hardware, TTY real ou sleep real.
- Mensagens em PT-BR; erros acionáveis e sem traceback na CLI.
- Limite de captura `32 MiB`; parar antes de excedê-lo, preservando captura parcial.
- Escritas atômicas para relatório e perfil; abort idempotente e cleanup da sessão em `finally`.

## Modelo de dados e unidades

- Frames são `RawFrame`: `device_id`, `timestamp_ns` inteiro em nanossegundos, mapas raw inteiros de axes/triggers e botões. JSONL aceita exatamente esses campos; `buttons` é serializado em ordem lexical e `allow_nan=False`.
- `DeviceSession` timestamps são monotônicos. `Clock.now_ns()` e os frames usam o mesmo domínio monotônico; o clock controla deadlines, enquanto o timestamp do frame permanece fonte do instante de amostragem.
- Writer subtrai do timestamp de cada frame o timestamp do primeiro frame e aplica o mesmo offset aos limites do manifesto. Os intervalos são semiabertos `[start_ns, end_ns)`.
- Limites finais derivam dos frames observados: `start_ns >= ts_first`, `end_ns <= ts_last + 1`; segmento sem intervalo observado é falha de qualidade e não entra como janela vazia no manifesto.
- Segmentos de retry substituem somente a janela antiga do mesmo alvo. Frames excluídos continuam na captura, fora de qualquer segmento.
- Manifesto v1: basename da captura, SHA-256 após flush, dispositivo, conexão `unknown` se não observada, segmentos ordenados e sem sobreposição. Como `LinuxEvdevBackend` atual não fornece VID/PID, o adapter registra `0x0000` para campo ausente e identifica a limitação no resumo; o valor significa desconhecido, nunca identificação inferida. Nome exibido usa o `DeviceInfo.name` existente.
- Nome de diretório usa timestamp UTC civil de fábrica separada do relógio monotônico mais `device_id` sanitizado; colisões ganham sufixos determinísticos `-2`, `-3` etc.
- Perfil mantém schema v1 e é validado pela implementação existente.

## UX e protocolo

Boas-vindas descrevem movimentos, tempo nominal de captura (aprox. 81 s, mais contagens e pausas) e que a qualidade depende da cadência efetiva do controle. Antes de cada segmento declarado, apresentar instrução curta, aguardar Enter e fazer contagem regressiva de 3 s. Aquecimento tem instrução inicial e duração de 2 s.

| Ordem | Segmento | Duração padrão | Instrução resumida | Critério medido existente |
| --- | --- | ---: | --- | --- |
| 0 | Aquecimento, não declarado | 2 s | Deixe o controle conectado e sem tocar | Nenhum |
| 1 | `rest`, `warmup_ns=1 s` | 5 s | Mãos fora do controle | >=3 s efetivos, >=150 frames por canal; ao menos 2 blocos válidos de 1 s para drift |
| 2 | `circle(left,cw)` | 6 s | Na borda, 3 voltas horárias e passe do ponto inicial | >=2 voltas válidas; cada uma >=100 frames e cobertura exigida dos 24 bins |
| 3 | `circle(left,ccw)` | 6 s | Mesmo movimento anti-horário | Mesmo critério |
| 4 | `circle(right,cw)` | 6 s | Mesmo movimento no stick direito | Mesmo critério |
| 5 | `circle(right,ccw)` | 6 s | Mesmo movimento anti-horário | Mesmo critério |
| 6 | `trigger_sweep(left)` | **25 s** | Em cada ciclo: 0,5 s em repouso, 2 s pressionando, 0,5 s no fundo e 2 s soltando; repetir 5 vezes | >=3 ciclos válidos; pico >=0,8 e >=50 frames por fase |
| 7 | `trigger_sweep(right)` | **25 s** | Mesmo ciclo no gatilho direito: 0,5 s em repouso, 2 s pressionando, 0,5 s no fundo e 2 s soltando; repetir 5 vezes | Mesmo critério |

As durações de círculos, sticks e triggers são defaults de orientação, não garantia de validade: taxa de frames e execução dos gestos determinam o resultado do motor. Para triggers, 25 s segue a sequência já descrita em `metrics-v1` (5 ciclos de cerca de 5 s); os 12 s do prompt 03 conflitam com essa sequência e são substituídos. Duração customizada permanece possível; qualidade continua sendo decidida exclusivamente por `execute_measure`.

Repouso de 5 s contém 1 s de warmup e 4 s efetivos, alinhado aos blocos de drift e ao mínimo de 3 s. Em evdev, ausência de evento não é amostra de repouso; portanto 150 frames não são garantidos por duração. Exibir instrução para não tocar, e deixar o motor reportar insuficiência. O segundo stick fica solto durante cada círculo.

## State machine e contratos

Reducer puro `step(state, event) -> (new_state, effects)`. Estado guarda dispositivo escolhido, fase, plano/índice de segmento, janelas atuais, contadores por alvo/global, outcome e artefatos. Fases: `WELCOME`, `SELECT_DEVICE`, `VALIDATE_MAPPING`, `CONFIRM_DEVICE`, `WARMUP`, `SEGMENT_PROMPT`, `COUNTDOWN`, `RECORD_SEGMENT`, `MEASURE`, `REVIEW`, `RETRY_DECISION`, `SAVE_DECISION`, `SAVE`, `SUMMARY`, `ABORTED`, `FAILED`.

Eventos tipados: confirmação/escolha/cancelamento, segmento concluído, medição concluída, retry aceito e decisão de salvar. Efeitos explícitos: exibir instrução/progresso/achados, seleção/confirmação, capturar/flush/finish/abort, medir, gravar relatório e salvar perfil. O driver na borda executa efeitos e devolve eventos. Cancelamento de qualquer fase converge para cleanup idempotente.

Portas propostas:

- `Console`: `is_interactive`, `say`, `ask_choice`, `ask_confirm`, `show_progress`, `show_findings`.
- `Clock`: `now_ns()` monotônico e espera injetável (`sleep(seconds)`); nenhuma chamada de sleep ou relógio dentro do reducer. O adapter relógio é a única borda que chama `time.sleep`/`time.monotonic_ns`.
- `CaptureSession`: `device_info`, `record_segment(spec, progress) -> Segment`, `flush()`, `finish() -> CaptureArtifacts`, `abort() -> Path`, `close()`. Adapter envolve `DeviceSession` e writer.
- `MeasureRunner`: recebe captura/manifesto, mapping e configuração e retorna `MeasureOutcome`; implementação monta `MeasureInputs`, usa `read_strict_capture`, `load_manifest` e `execute_measure`.
- Reutilizar `DeviceBackend`, `ProfileStore` e `JsonProfileStore` existentes.

## Política de retry

Elegíveis, conforme `finding.code` e `finding.metric`:

| Achado | Alvo que substitui |
| --- | --- |
| `REST_TOO_SHORT`, `HIGH_DRIFT`, `HIGH_NOISE` | Único segmento `rest` |
| `INSUFFICIENT_CIRCLE_POINTS`, `INSUFFICIENT_CIRCLE_LAPS`, `CIRCLE_DIRECTION_INCONSISTENT` | Stick e direção identificados pelo caminho `metric` |
| `INSUFFICIENT_TRIGGER_CYCLES` | Trigger identificado pelo caminho `metric` |

Só oferecer retry quando os achados bloqueantes relevantes resolverem para alvos existentes e elegíveis; sem alvo seguro, interromper com qualidade bloqueante. Limite padrão: 2 retries por alvo e 6 retries globais. Se um retry de repouso persistir por baixa emissão de frames, informar o escopo/métrica e encerrar ao esgotar tentativas. Achados não bloqueantes `LOW_CIRCULARITY`, `SATURATION_HIGH`, `LOW_TRIGGER_R2`, `HIGH_HYSTERESIS` são apenas exibidos. Achados de mapping, ranges degenerados, canais ausentes, timestamps inválidos, taxa fora de tolerância e deadzone clamp não disparam retry.

## Exit codes

| Código | Situação |
| ---: | --- |
| 0 | Perfil salvo ou usuário recusou salvar resultado aceito |
| 1 | Falha inesperada acionável |
| 2 | Argumentos, TTY, mapping, thresholds, manifesto ou captura inválidos |
| 3 | Dispositivo indisponível, desconectado ou sem permissão |
| 4 | Qualidade bloqueante sem retry disponível/aceito ou perfil não derivável |
| 130 | Ctrl+C, EOF ou cancelamento explícito |

Cancelamento antes de concluir protocolo preserva `capture.jsonl` parcial e não grava manifesto, relatórios ou perfil. Desconexão igualmente não gera perfil e preserva a captura parcial para diagnóstico. Protocolo completo com resultado sem perfil aceitável preserva captura, manifesto e relatórios.

## Impacto por camada

- `domain`: sem novas fórmulas; tipos de evento/estado podem ficar na aplicação.
- `application`: novo caso de uso reducer/driver e portas de console/clock/captura/medição; adaptador runner invoca os contratos já existentes.
- `infrastructure`: writer compatível com leitores estritos, relógio e runner.
- `interface`: `terminal_console.py`, parser e composição de `calibrate`; demais comandos permanecem inalterados.
- Persistência: somente perfil v1 pelo `JsonProfileStore`; relatório usa `dumps_report`, `render_markdown`, `write_text_atomic`.
- Documentação: este arquivo, ADR 0005 e README após aprovação/implementação.

## Artefatos

Diretório de sessão: `<capture-dir>/<UTC>-<device>/` com `capture.jsonl`, `capture.manifest.json`, `report.json`, `report.md`. `capture_file` é basename. Cada flush escreve JSONL consistente e manifesto atualizado. `finish()` fecha e finaliza hash/manifesto. `abort()` fecha arquivo e dispositivo idempotentemente; em protocolo incompleto não deixa manifesto/report/perfil.

CLI proposta: `calibrate [--device ID] --mapping PATH [--capture-dir PATH] [--profiles-dir PATH] [--thresholds PATH] [--warmup-seconds 2] [--rest-seconds 5] [--circle-seconds 6] [--trigger-seconds 25] [--max-retries 2]`. Argumentos de duração devem ser finitos e positivos. Antes de abrir dispositivo, repouso deve comportar warmup + duração efetiva mínima configurada. O limite de amostras por círculo/fase não pode ser validado por duração sem taxa nominal conhecida; esses critérios permanecem no relatório de qualidade.

## Plano de testes

- Reducer: ordem feliz, transições inválidas, retry aceito/recusado, limites por alvo e global, cancelamento em cada fase.
- Writer: schema exato, botões ordenados, UTF-8/JSON válido sem NaN, timestamp monotônico/rebase, hash, basename, segmentos ordenados e não sobrepostos, retry remove janela antiga, abort e limite de 32 MiB.
- Runner: fixtures passam por `read_strict_capture`/`load_manifest`, chamam `execute_measure` estrito e refletem outcome sem recalcular qualidade; report é salvo antes do perfil.
- CLI com console roteirizado: sem TTY, mapping inválido antes de abrir, seleção manual, dispositivo ausente, desconexão, cancelamento, pass/warn, recusa e cada exit code.
- Integração fake: perfil v1 carrega no store, captura reexecuta com `measure`, retries reavaliam tudo; regressões dos comandos existentes.
- Nenhum teste usa `/dev/input`, `/dev/uinput`, TTY real, sleep real ou hardware.

## Riscos

- Evdev pode não emitir frames repetidos enquanto imóvel; mínimo de 150 amostras de repouso pode falhar apesar dos 5 s.
- Cadência e movimento real podem impedir 100 frames/volta ou 50 frames/fase; defaults orientam e métricas aceitam/rejeitam.
- Rebase/limites inconsistentes invalidam o manifesto; mesmo offset e clamp aos frames observados são obrigatórios.
- VID/PID ausentes são representados por `0x0000` e não identificam a família do controle; descoberta é incremento posterior.
- Retry de mapping inadequado desperdiça movimento; achados sem mapping seguro abortam sem perfil.
- Smoke, compatibilidade com hardware real e plausibilidade prática dos defaults permanecem não verificados sem autorização do usuário.

## Critérios de aceite

- `calibrate --help` documenta argumentos, TTY e exit codes; `--help` funciona sem TTY.
- Comandos existentes permanecem inalterados e compatíveis.
- Mapping/thresholds e TTY inválidos falham antes de abrir dispositivo.
- Captura/manifesto são aceitos sem edição por `read_strict_capture`/`load_manifest` e pelo fluxo `measure`.
- Segmentos compartilham domínio monotônico rebaseado, são ordenados, semiabertos e não sobrepostos.
- State machine não executa input/print/sleep nem lê clock diretamente; portas são injetáveis.
- Perfil v1 válido é salvo uma vez depois dos relatórios; nenhum perfil é salvo em cancelamento, desconexão, qualidade bloqueante ou derivação inválida.
- Retry mapeia apenas alvos seguros, substitui a janela e respeita 2 por alvo/6 global.
- Testes determinísticos cobrem caminho feliz, warn/recusa, retry, erros, bordas de timestamp, cancelamento, tamanho e compatibilidade.
- ADR 0005 e README registram contrato, limitações e seleção manual.

## Decisões D1–D10

| ID | Decisão nesta spec | Dono |
| --- | --- | --- |
| D1 | Console PT-BR simples, menus numerados, TTY e confirmação explícita | Python + produto |
| D2 | Reducer puro em `application/calibrate.py`; efeitos em portas | Python |
| D3 | 2 s warmup, 5 s rest (1 s warmup interno), 6 s por círculo, **25 s por trigger** | Hardware |
| D4 | Retry 2/alvo, 6 global; somente códigos elegíveis e alvo resolvido por `metric` | Hardware |
| D5 | Diretório único UTC/device com captura, manifesto e relatórios | Python |
| D6 | Domínio monotônico compartilhado; rebase único; limites derivados/clampados por frames | Hardware + Python |
| D7 | `execute_measure(strict=True, save_profile=True)` em processo; sem duplicar qualidade | Python |
| D8 | Relatórios antes de persistir via `JsonProfileStore`; nunca salvar perfil ausente | Python |
| D9 | Cancelamento retorna 130, preserva captura parcial e não gera artefatos finais/perfil | Python |
| D10 | Console/sessão/clock/runner injetados; testes fake sem hardware ou sleep real | Python |

## Decisões aprovadas pelo usuário em 2026-10-25

1. Aprovado: 25 s por trigger no lugar de 12 s, pois o protocolo já definido em `metrics-v1` descreve cinco ciclos com cerca de 5 s cada.
2. Aprovado: `0x0000` como representação explícita de VID/PID desconhecidos no backend evdev atual, com aviso no resumo.
3. Aprovado: duração menor que 25 s é configurável e a avaliação continua com `execute_measure`; as métricas existentes decidem a qualidade observada.
4. Aprovado: estimativa de cerca de 81 s de captura nominal, acrescida de contagens regressivas e tempo de interação.

