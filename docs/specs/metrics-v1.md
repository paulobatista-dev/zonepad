# Spec — Métricas de calibração v1 (`metrics_schema_version=1`)

- **Status:** aprovada pelo usuário em 2026-10-24, incluindo P1–P8 conforme as recomendações (ver "Decisões do usuário"). Decisão de schema e relatório: `docs/adr/0004-metricas-relatorio-separado-e-perfil-v1.md`.
- **Data:** 2026-10-24
- **Autor da semântica:** `controller-hardware`
- **Origem:** `ai/prompts/02-calibration-metrics.md`, etapa 2.
- **Convenção de evidência:** **[F]** fato verificado no código ou na saída de um comando (com `arquivo:linha`); **[I]** inferência; **[S]** suposição; **[L]** lacuna (não verificado). Números marcados *"default a validar"* não têm amostra real que os sustente.

## Problema

O ZonaPad hoje deriva um perfil com `build_profile` (`src/zonepad/application/calibration.py:17-72`), que usa média para o centro (`:31-33`), `min`/`max` crus para os ranges (`:34-35`) e `epsilon` silencioso de `1e-6` quando o centro encosta no extremo (`:37-42`, `:51-56`). Não existe medição de repouso, ruído, drift, circularidade, linearidade, histerese nem taxa. A deadzone de todo perfil gerado é `0` (`DeadzoneSpec` padrão, `domain/profile.py:89-91`). Um outlier ou um toque acidental muda centro e range, e nada avisa o usuário.

## Usuário e contexto

Pessoa que tem um controle (alvos: Xbox, DualShock/DualSense, Switch Pro, 8BitDo, HID genérico) e quer um perfil reproduzível a partir de uma captura raw. Ambiente: Linux, backend evdev (`infrastructure/evdev.py`), captura JSONL lida por `infrastructure/replay.py`. O wizard interativo (prompt 03) vai orquestrar este motor; esta spec não define UX.

## Resultado esperado

1. Cada métrica tem camada, unidade, fórmula e janela exatas, de modo que duas implementações independentes produzam o mesmo número (tolerância `1e-9` em testes sintéticos).
2. Um protocolo de captura com segmentos declarados num manifesto sidecar e mínimos de amostra por segmento e por volta.
3. Cada violação do protocolo ou de um threshold vira um achado com código estável, severidade e regra de bloqueio em `--strict`.
4. Um perfil `schema_version=1` derivado das métricas, que passa em `validate_profile` ou não é gerado (com erro acionável).

## Escopo

- Métricas de sticks, triggers e captura (seção "Modelo de dados e unidades").
- Protocolo de captura, manifesto `manifest_version=1`, arquivo de thresholds.
- Relatório `metrics_schema_version=1` / `report_kind="calibration-metrics"`, derivação de `quality.status`.
- Derivação do perfil v1 (centro, ranges, deadzone, rest/max, curva, inversão).
- Decisões D1–D10 do prompt.

## Fora de escopo

- Wizard, GUI, descoberta/hot-plug, mapeamento automático (prompts 03–05).
- Medição de deadzone de firmware, inferência de curva/inversão, correção de gate não circular.
- Botões (o protocolo da skill os lista, mas `measure` v1 os ignora).
- Comparação entre sessões repetidas (cada captura é uma sessão; ver Decisões pendentes).
- Escrita do código, dos testes e da ADR (etapas 3–8).

## Contexto verificado no código

| # | Fato | Evidência |
| --- | --- | --- |
| C1 | Frames do JSONL são `RawFrame` (inteiros evdev). `load_capture` usa `json.loads` (aceita `NaN`/`Infinity`), converte `timestamp_ns` com `int()` (aceita float/str/bool) e repassa `axes`/`triggers` sem validar tipo. Erro devolve só o número da linha. | `infrastructure/replay.py:17-28`; `domain/input.py:24-25` (só rejeita `timestamp_ns < 0`) |
| C2 | O runtime normaliza **cada frame com o mapping** (`min/center/max`, `rest/max`) e só então aplica o perfil. O perfil vive no espaço normalizado. | `application/runtime.py:41-42`; `domain/normalization.py:30-43`; ADR 0003 |
| C3 | A normalização **clampa** em `[-1,1]` / `[0,1]` e levanta `ValueError` para canal sem range. | `domain/normalization.py:37`, `:43`, `:64` |
| C4 | Nomes canônicos: eixos `lx ly rx ry`; triggers `lt rt`. | `infrastructure/mapping.py:12-13` |
| C5 | A calibração do perfil aplica `centro -> range -> deadzone radial -> curva -> inversão`; a deadzone atua em coordenadas **já calibradas** (divididas pelo semi-range). `cut` mantém o vetor fora da zona sem alteração. | `domain/calibration.py:45-50`, `:53-64`, `:29-42` |
| C6 | Trigger: `scaled = clamp((v-rest)/(max-rest))`; deadzone é fração do **span**, com rescale. | `domain/calibration.py:72-81` |
| C7 | Invariantes do perfil: centro e ranges em `[-1,1]`; `range_min < center < range_max` (estrito); deadzone em `[0,0.95]`; trigger `0 <= rest < max <= 1`; `left` e `right` obrigatórios; `profile_id` UUID v4; `created_at` UTC; `notes <= 2000`. | `domain/profile.py:94`, `:126-137`, `:187-190`, `:285-292`, `:296-301`, `:306` |
| C8 | `evdev` emite um `RawFrame` por `SYN_REPORT`, com timestamp = `time.monotonic_ns()` no instante da leitura, não o horário do evento. O construtor fixa `_timestamp_mode = "read_monotonic"` (`:49`); o ramo `event_timeval` (`CLOCK_REALTIME` do kernel) só roda em instâncias criadas sem `__init__` (`tests/test_runtime_cli.py:198`, `object.__new__`). Verificado em revisão (`grep` de `_timestamp_mode`). Consequência: eventos lidos em rajada na mesma ativação do `select` recebem timestamps quase iguais, o que distorce `rate_p5/p95` (a média `1/mean(Δt)` permanece válida). | `infrastructure/evdev.py:47-49`, `:100-103` |
| C9 | O projeto não tem dependências de runtime (`dependencies = []`); métricas usam `statistics`/`math` da stdlib. | `pyproject.toml:13` |
| C10 | `JsonProfileStore.save` grava com `sort_keys=True` e escrita atômica. | `infrastructure/json_profile_store.py:38-50` |

## Requisitos funcionais

- **RF1** Entrada: captura JSONL, manifesto, mapping (mesmo JSON do `run`) e thresholds opcionais.
- **RF2** Todas as métricas são calculadas sobre frames **normalizados com o mapping** (C2); a camada raw aparece só como diagnóstico `raw.*`.
- **RF3** O relatório inclui mediana/valor típico **e** pior caso/p99 de cada métrica de dispersão.
- **RF4** Série vazia, divisão por zero, eixo ausente e valor não finito geram achado ou erro de entrada; o relatório nunca contém `NaN`/`Infinity` e nenhuma métrica `null` existe sem achado cujo `metric` a nomeie. Um achado "nomeia" uma métrica quando seu `metric` é o caminho dela ou um ancestral (por segmentos separados por ponto): `MISSING_CIRCLE_SEGMENT` com `metric="sticks.left"` cobre todo `sticks.left.range.*`.
- **RF5** O perfil só é gerado se não houver achado `error`; ele nunca usa epsilon.
- **RF6** O relatório registra thresholds efetivos, parâmetros de protocolo efetivos, hash SHA-256 da captura e do mapping.

## Requisitos não funcionais

- Domínio puro (stdlib), sem IO. Mesmos bytes de entrada + mesmo relógio/UUID injetados ⇒ mesmo relatório e mesmo perfil (byte a byte).
- Floats serializados com `round(x, 6)` (taxas em Hz: `round(x, 3)`); `-0.0` vira `0.0`; `json.dumps(..., allow_nan=False, sort_keys=True, indent=2, ensure_ascii=False)`.
- Memória da captura (v1): o leitor carrega todos os frames em memória (medido: ~1,1 KB residente por frame; 63 012 frames a 1 kHz ocupam ~70 MB, pico ~100 MB). O leitor rejeita capturas acima de **32 MiB** (`[INVALID_CAPTURE]`, ~220 mil frames, ~250 MB), que cobrem mais de 3 min a 1 kHz. Streaming com janela fica para uma versão futura, com o mesmo contrato de métricas.
- Privacidade: o relatório e o Markdown trazem `device.name/vid/pid` e o **basename** da captura; `serial`, `guid` e paths absolutos nunca entram no relatório (o perfil local pode levar `guid`/`serial` do manifesto).
- Tamanhos máximos de entrada: manifesto <= 1 MiB e <= 256 segmentos; thresholds <= 64 KiB (guarda contra entrada hostil).

## Modelo de dados e unidades

### Convenções numéricas (fixas por `metrics_schema_version=1`)

- **Tempo:** `t_i = timestamp_ns_i / 1e9` em segundos. Intervalos de segmento são **semiabertos** `[start_ns, end_ns)`; uma amostra pertence ao segmento se `start_ns <= ts < end_ns`.
- **Percentil `q`** (`q` em `[0,1]`): interpolação linear (Hyndman-Fan tipo 7). Para a amostra ordenada `x_0 <= ... <= x_{n-1}` e `h = (n-1)q`: `P_q = x_floor(h) + (h - floor(h)) * (x_ceil(h) - x_floor(h))`. Equivale a `statistics.quantiles(method="inclusive")`. Para `n = 1`, `P_q = x_0`. A **mediana** é `P_0.5` (para `n` par, média dos dois centrais).
- **Eixo de um stick:** `left = (lx, ly)`, `right = (rx, ry)`. **Trigger:** `left = lt`, `right = rt`. Os nomes `left/right` valem no manifesto, no relatório e no perfil.
- **Camada padrão:** normalizado (stick `[-1,1]`, trigger `[0,1]`). Camada raw só em `raw.*` (counts inteiros). Calibrado (após perfil) aparece apenas em `deadzone_suggested`, que é definida nesse espaço porque a deadzone do runtime atua nele (C5, C6).
- `n(t)` = valor normalizado do trigger; `p(t) = (x(t), y(t))` = posição normalizada do stick; `c` = centro de repouso do stick; `e(t) = p(t) - c`.

### Métricas de stick (por `left`/`right`; camada: normalizado salvo nota)

Frame **válido para o stick** = contém os dois eixos do stick. Frames sem um dos eixos são excluídos daquele stick e contados (achado `AXIS_MISSING`). Ausência de evento não é repouso (C8): só frames emitidos contam.

| Métrica | Janela | Definição exata | Unidade |
| --- | --- | --- | --- |
| `center` | amostras efetivas de todos os `rest`, agrupadas | mediana por eixo: `c = (P_0.5(x), P_0.5(y))` | `[-1,1]` |
| `center_segment_max_shift` | cada `rest` | `max_s ‖median_s - c‖` (mediana 2D de cada segmento `s` contra `c`); `0` com um só segmento | `[-1,1]` |
| `rest.noise_rms.{x,y}` | idem | `sqrt(mean_t(e_a(t)^2))`, `a ∈ {x,y}` | `[-1,1]` |
| `rest.noise_rms.xy` | idem | `sqrt(mean_t(‖e(t)‖^2))` | `[-1,1]` |
| `rest.noise_p2p.{x,y}` | idem | `max_t a(t) - min_t a(t)` | `[-1,1]` |
| `rest.noise_radius.{max,p99}` | idem | `max_t ‖e(t)‖` e `P_0.99(‖e(t)‖)` | `[-1,1]` |
| `rest.drift` | blocos de 1 s (ver abaixo) | `max_k ‖m_k - c‖`, com `m_k` = mediana por eixo do bloco `k` | `[-1,1]` |
| `rest.jitter.{mean,p99,max}` | pares consecutivos dentro do mesmo `rest` efetivo | `‖p_{i+1} - p_i‖` (2D); média, `P_0.99`, máximo | `[-1,1]` |
| `range.min/max` | todos os frames válidos dos segmentos `circle` do stick | por eixo: `P_0.005` e `P_0.995` | `[-1,1]` |
| `range.observed_min/max` | idem | mínimo e máximo absolutos (pior caso) | `[-1,1]` |
| `range.span` | idem | `max - min` por eixo | `[0,2]` |
| `range.symmetry` | idem | `(max - c) / (c - min)` por eixo; ideal `1`; `null` + `CENTER_OUTSIDE_RANGE` se `c - min <= 0` **ou** `max - c <= 0` (os dois semi-ranges precisam ser positivos; valor negativo não existe) | adimensional |
| `circle.circularity.{median,worst}` | voltas válidas (ver abaixo) | por volta: `min_k R_k / max_k R_k`; mediana e mínimo entre voltas válidas | adimensional |
| `circle.mean_radius.{median,worst}` | idem | por volta: média de `r_i`; mediana e mínimo entre voltas | `[-1,1]` |
| `circle.saturation_ratio` | frames válidos dos `circle` | fração com `max(abs(x),abs(y)) >= 1 - 1e-9` | `[0,1]` |
| `deadzone_suggested.value` | repouso, no espaço calibrado | ver "Algoritmo da deadzone" | `[0,0.95]` radial |

**Drift (separação de ruído).** `drift` mede a deriva lenta; `noise_*` mede a variação rápida. Para cada segmento `rest` efetivo, particione em blocos **consecutivos de 1,0 s**, a partir de `start_ns + warmup_ns`; descarte o resto final menor que 1 s e blocos com menos de 5 frames. `m_k` = mediana por eixo dos frames do bloco. Com menos de 2 blocos válidos no total: `drift = null` e achado `REST_TOO_SHORT`. Justificativa: a skill e o prompt definem `drift` e `noise_radius.max` pela mesma fórmula `max‖p-c‖`, o que torna os dois thresholds redundantes; a escala de tempo (blocos de 1 s) dá ao `drift` um significado próprio: ele ignora a variação rápida dentro do bloco. A janela de 4 s do protocolo mede deriva de curto prazo, **não** deriva térmica (ver Riscos).

**Relação entre drift e ruído (decisão de revisão).** O `drift` é o erro residual que um perfil de centro único `c` comete no instante do bloco `k`; por isso a referência é o centro global e não o primeiro bloco. As métricas `noise_*` também usam `e(t) = p(t) - c` (a skill define o ruído em torno de `c`, e a deadzone precisa cobrir toda a excursão ao redor de `c`). Logo uma deriva lenta **entra** em `noise_rms`: a separação vale só no sentido `drift` ignora o ruído rápido, não no inverso. Para uma rampa linear de amplitude `D` em 4 blocos de 1 s, `drift = 3D/8` e `noise_rms ≈ 0,29·D`; `HIGH_DRIFT` e `HIGH_NOISE` disparam juntos. Medir o ruído contra o centro local do bloco ficaria para uma versão futura.

**Descarte `warmup_ns`.** Em cada `rest`, a janela efetiva é `[start_ns + warmup_ns, end_ns)`. Frames em `[start_ns, start_ns + warmup_ns)` não entram em nenhuma métrica de repouso nem na contagem de mínimos; entram em `capture.frames`.

**Voltas do círculo (por segmento `circle`, usando `c` do repouso).**

1. `v_i = p_i - c`, `r_i = ‖v_i‖`, `θ_i = atan2(v_y, v_x)`. Mantenha só os frames com `r_i >= 0.3` (`circle_min_radius`); abaixo disso o ângulo é dominado por ruído (com ruído <= 0,02, o erro angular é <= `atan(0.02/0.3) ≈ 3,8°` — inferência, valor a validar).
2. Desenrole o ângulo: `Θ_0 = θ_0`; `Θ_i = Θ_{i-1} + wrap(θ_i - θ_{i-1})`, com `wrap` para `(-π, π]`.
3. `s = sign(Θ_last - Θ_0)`; voltas completas `L = floor(|Θ_last - Θ_0| / 2π)`. A volta `k` (0-based) contém os frames com `s·(Θ_i - Θ_0) ∈ [2πk, 2π(k+1))`. O resto parcial é descartado das métricas de volta, mas conta para `range`. **Volta completa exige `|Θ_last - Θ_0| >= 2π` de fato:** `N` amostras igualmente espaçadas em exatamente uma revolução cobrem só `2π(N-1)/N` e dão `L = 0`; para obter `L = 1` a captura precisa de pelo menos um passo além do ponto inicial. O protocolo pede 3 voltas e exige 2 válidas por direção; essa margem de uma volta absorve um ponto de partida ou parada imperfeito, e o wizard deve instruir "continue um pouco além do ponto de partida".
4. Divida o ângulo `θ` de cada frame da volta em **24 bins de 15°, centrados em múltiplos de 15°**: `bin = floor((θ + 7.5°)/15°) mod 24`. `R_k` = mediana de `r_i` no bin `k`.
5. **Volta válida** = `>= 100` frames (`circle_min_points_per_lap`, valor da skill) **e** todos os 24 bins com `>= 2` frames. Volta inválida gera `INSUFFICIENT_CIRCLE_POINTS` e não entra em circularidade/raio médio.
6. A direção observada `s` é só consistência: todas as voltas rotuladas `cw` do mesmo stick devem ter o mesmo `s`, e `ccw` o oposto; senão `CIRCLE_DIRECTION_INCONSISTENT`. Esta spec não assume a convenção de sinal do eixo Y (evdev costuma reportar Y positivo para baixo — **[I]**, depende do mapping), então o rótulo `cw`/`ccw` é a instrução dada ao usuário, não uma verdade geométrica. **Limite assumido (decisão de revisão):** se o usuário troca os dois rótulos ao mesmo tempo, nenhum teste de consistência detecta, e nenhuma métrica ou campo do perfil depende de `cw` versus `ccw` (só a contagem de voltas por direção), então o resultado numérico permanece correto. Detectar a troca exigiria declarar a convenção de Y no mapping (campo futuro, fora do v1).
7. **Transiente de entrada.** As voltas começam no primeiro frame com `r >= circle_min_radius`. Se o usuário sai do centro em espiral, a volta 0 inclui o trecho de `r` crescente e `circularity.worst`/`mean_radius.worst` ficam pessimistas mesmo num gate perfeito (medido em revisão: espiral de 0,5 s ⇒ `circularity.worst = 0,39` com `median = 1,0`). O `LOW_CIRCULARITY` usa a mediana e não é afetado. O wizard deve iniciar o segmento com o stick já na borda; o corte do transiente por raio relativo fica como decisão pós-captura real (etapa 9).

**Algoritmo da deadzone sugerida (stick).**

1. Derive `range_min/range_max` e `center` (acima).
2. Para cada frame de repouso efetivo, calcule `ĉ = _calibrate_axis(p; c, range_min, range_max)` por eixo, exatamente como `domain/calibration.py:45-50`, e `ρ = hypot(ĉ_x, ĉ_y)`.
3. `dz = clamp(max(factor · P_0.99(ρ), stick_floor), 0, 0.95)`, `factor = 1.5`, `stick_floor = 0.02`, modo `cut`.
4. Se o clamp em `0.95` atuar, achado `DEADZONE_CLAMPED`.

Justificativas: (a) o espaço calibrado é o espaço onde `apply_radial_deadzone` atua (C5); como o semi-range é `<= 1`, `ρ` é `>=` o raio normalizado, ou seja, a escolha é a mais conservadora. (b) `factor = 1.5`: sob ruído gaussiano 2D isotrópico (raio de Rayleigh), `P_0.99 = σ·√(2 ln 100) ≈ 3,03σ` e `P_0.9999 = σ·√(2 ln 10^4) ≈ 4,29σ`; a razão é `≈ 1,41`, então `1,5` cobre um percentil 99,99 de uma janela mais longa. **[I]** depende de o ruído ser gaussiano; **default a validar em amostra maior**. (c) `stick_floor = 0.02` iguala o `drift_max`: qualquer repouso que o critério de aceite tolera deve ser zerado, mesmo quando a medição vê ruído zero (por exemplo, deadzone de firmware escondendo o ruído). **default a validar**. Lacuna: deadzone de firmware não é medida nesta versão (ver Decisões pendentes), então a deadzone de software pode somar-se a uma de firmware.

### Métricas de trigger (por `left`/`right`; camada: normalizado `[0,1]`)

| Métrica | Definição | Unidade |
| --- | --- | --- |
| `rest` | `P_0.5(n)` nos frames de repouso efetivos | `[0,1]` |
| `rest.noise_rms` | `sqrt(mean((n - rest)^2))` no repouso | `[0,1]` |
| `rest.noise_p2p` | `max(n) - min(n)` no repouso | `[0,1]` |
| `rest.noise_p99` | `P_0.99(abs(n - rest))` no repouso | `[0,1]` |
| `max` | mediana dos picos `m_k` dos ciclos válidos | `[0,1]` |
| `span` | `max - rest` | `[0,1]` |
| `max_dispersion` | `max_k m_k - min_k m_k` | `[0,1]` |
| `linearity_r2.{median,worst}` | R² por fase, ver abaixo; mediana e mínimo | adimensional |
| `linearity_max_error.{median,worst}` | erro absoluto máximo por fase, em unidades de `n`; mediana e máximo | `[0,1]` |
| `hysteresis.{median,worst}` | por ciclo, ver abaixo; mediana e máximo | `[0,1]` |
| `saturation_ratio` | fração dos frames dos `trigger_sweep` com `n >= 1 - 1e-9` | `[0,1]` |
| `deadzone_suggested.value` | ver abaixo | fração do span `[0,0.95]` |

**Detecção de ciclos (em cada `trigger_sweep`).**

1. `s(t)` = mediana móvel de janela 5 de `n(t)` dentro do segmento (bordas: janela reduzida). Todas as métricas de forma usam `s`; ruído em repouso e saturação usam `n` bruto.
2. Máquina de estados com histerese, **relativa ao repouso medido** `rest` (`s` já normalizado pelo mapping, então `rest ≈ 0` quando o mapping está certo): **arma** ao primeiro frame com `s - rest > 0.15` (`trigger_arm`); **encerra** ao primeiro frame seguinte com `s - rest <= 0.10` (`trigger_exit`). Ciclo que não encerra antes do fim do segmento é descartado. (Com limiares absolutos, um repouso medido acima de `0.10` mantém o ciclo armado para sempre e o resultado vira "0 ciclos detectados" sem explicar a causa; medido em revisão com repouso `0.2`.)
3. `m_k = max s` no ciclo; `p_k` = primeiro índice do máximo.
4. **Ciclo válido** = `m_k >= 0.8` (`trigger_peak_min`, absoluto, em unidades normalizadas), e `>= 50` frames **medidos** em cada fase (`trigger_phase_min_points`; os dois pontos interpolados das âncoras não contam), com as fases definidas abaixo. Sem ciclo válido, o mapping provavelmente tem `max` alto demais ou o usuário não pressionou até o fundo.
5. **Janela de busca das âncoras.** As âncoras 0,05 ficam fora da faixa de histerese (`s - rest` cruza 0,05 antes de chegar a `arm = 0,15` e volta a cruzá-lo depois de `exit = 0,10`). Por isso as fases do ciclo `k` são procuradas no **contexto** do ciclo: do primeiro frame após o encerramento do ciclo anterior (ou início do segmento) até o frame anterior ao armamento do próximo ciclo (ou fim do segmento). `y`, `t_a`, `t_b`, `t_c` e `t_d` abaixo usam só os frames do contexto. Ciclo cujo contexto não contém os quatro cruzamentos é inválido (`INSUFFICIENT_TRIGGER_CYCLES`).

**Fases e forma.** `y(t) = (s(t) - rest) / (m_k - rest)`.

- Subida: `t_b` = primeiro cruzamento ascendente de `0.95` no ciclo; `t_a` = último cruzamento ascendente de `0.05` antes de `t_b`.
- Descida: `t_c` = último cruzamento descendente de `0.95` no ciclo; `t_d` = primeiro cruzamento descendente de `0.05` depois de `t_c`.
- Cruzamentos por interpolação linear entre os frames vizinhos. A fase contém os frames com `t` estritamente entre as duas âncoras mais os dois pontos interpolados das âncoras.
- Progresso: subida `τ = (t - t_a)/(t_b - t_a)`; descida `τ = (t_d - t)/(t_d - t_c)` (ambos `0` no repouso e `1` no fundo).

**Linearidade (por fase).** Reta de referência pelas âncoras: `ŷ(τ) = 0.05 + 0.90·τ`. `R² = 1 - Σ(y - ŷ)^2 / Σ(y - ȳ)^2` (não clampado; denominador nunca zero porque `y` varia de 0.05 a 0.95). `linearity_max_error = (m_k - rest) · max|y - ŷ|`. Cada ciclo contribui com duas fases (subida, descida); a mediana e o pior caso são calculados sobre o conjunto.

**Histerese (por ciclo).** Grade `x_j = j/100`, `j = 0..100`. `y_up(x_j)` e `y_down(x_j)` = interpolação linear de `y` contra `τ` em cada fase. `hysteresis_k = (m_k - rest) · max_j |y_up(x_j) - y_down(x_j)|`.

> **Limitação de princípio [I, alta confiança].** `linearity_*` e `hysteresis` usam o **tempo normalizado como proxy da posição do gatilho**, porque a captura tem um único canal (o valor do trigger) e nenhum sensor de curso. Elas medem aderência a uma rampa de velocidade constante e assimetria entre subida e descida, e misturam o perfil de velocidade do dedo com o hardware. Ancorar as fases nos mesmos níveis (0,05/0,95) elimina deslocamentos verticais puros e atrasos (folga mecânica) de propósito, porque eles não são distinguíveis do tempo de reação humano. Por isso o relatório rotula `shape_basis: "time_normalized"` e os achados `LOW_TRIGGER_R2`/`HIGH_HYSTERESIS` têm severidade `info` (ver Decisões D11 e P4).

**Deadzone sugerida (trigger).** `dz = clamp(max(factor · rest.noise_p99, trigger_floor) / (max - rest), 0, 0.95)`, com `trigger_floor = 0.01` (**default a validar**). A divisão pelo span converte unidades normalizadas na fração de span usada em `domain/calibration.py:72-81` (C6).

### Métricas de captura

| Métrica | Definição | Unidade |
| --- | --- | --- |
| `frames` | total de linhas válidas | contagem |
| `frames_outside_segments` | frames fora de qualquer janela de segmento | contagem |
| `duration_s` | `(ts_last - ts_first) / 1e9` | s |
| `effective_rate_hz` | `1 / mean(Δt)` sobre a população de pares abaixo | Hz |
| `rate_p5_hz`, `rate_p95_hz` | `P_0.05` e `P_0.95` do conjunto `{1/Δt}` da mesma população | Hz |
| `rate_pairs` | tamanho da população | contagem |
| `saturation_ratio` | por stick/trigger (acima) | `[0,1]` |

**População de pares (D8).** Pares consecutivos `(i, i+1)` com ambos os frames dentro do **mesmo segmento `circle`** (janela completa) e `0 < Δt <= 0.25 s` (`rate_gap_max_s`). Motivo: o evdev só emite frames em mudança de valor (**[I]**, o kernel filtra valores repetidos de ABS; não verificado aqui) e o `SYN_REPORT` é a unidade de frame (C8), então repouso e platôs de trigger têm intervalos que não são o período de relatório do controle. Só movimento contínuo (círculos) mede cadência. Com `rate_pairs < 100`: campos de taxa `null` e achado `RATE_UNAVAILABLE` (info). A **taxa nominal** vem do manifesto (`nominal_rate_hz`, opcional); sem ela, `NOMINAL_RATE_UNKNOWN` (info) e nenhuma checagem de tolerância. A taxa medida é a taxa dos frames lidos pelo ZonaPad com timestamp de leitura (C8), que inclui jitter de escalonamento e de Bluetooth.

**Timestamps (D8).** Qualquer `Δt < 0` na captura inteira ⇒ erro de entrada (exit 2, código `NON_MONOTONIC_TIME`, linha informada). `Δt = 0` ⇒ achado `DUPLICATE_TIMESTAMP` (warning); esses pares ficam fora da taxa.

### Diagnóstico raw (`raw.<canal>`, camada raw, counts)

Para cada canal usado: `mapping` (`minimum/center/maximum` ou `rest/maximum`), `rest_median`, `observed_min`, `observed_max`, `out_of_range_ratio` (fração dos frames dos segmentos com valor **estritamente** fora do intervalo do mapping, que a normalização clampa e esconderia, C3) e `lsb_normalized = 1 / min(maximum - center, center - minimum)` para eixos (`1/(maximum-rest)` para triggers). `out_of_range_ratio > 0` ⇒ `MAPPING_RANGE_EXCEEDED`.

### Entradas

**Mapping.** `--mapping` obrigatório, o mesmo JSON v1 de `zonepad run` (`infrastructure/mapping.py:64`, ADR 0003). Motivo: o perfil é aplicado a frames normalizados pelo mapping (C2); medir com outra normalização produziria centro e range incompatíveis com o runtime. Canais do JSONL que não existem no mapping são ignorados com `UNMAPPED_CHANNEL_IGNORED` (info) em vez de deixar `normalize_frame` levantar (C3). Aliases `left_trigger/right_trigger` do builder legado (`application/calibration.py:46-47`) não são aceitos aqui.

**Captura.** Estrita, diferente do `load_capture` atual (C1): cada linha é um objeto JSON; `timestamp_ns` é inteiro JSON `>= 0` (não bool, não float); valores de `axes`/`triggers` são inteiros JSON; `NaN`/`Infinity`/`-Infinity` são rejeitados na leitura (`parse_constant`); `device_id` é o mesmo em todas as linhas; erro cita arquivo e número da linha. Captura vazia ⇒ exit 2. O `load_capture` existente permanece intacto para `replay`; `measure` usa um leitor estrito próprio (decisão estrutural do `python-engineer`).

**Manifesto `manifest_version=1`.**

```json
{
  "manifest_version": 1,
  "device": {"device_id": "event3", "name": "Xbox Wireless Controller", "vid": "0x045e", "pid": "0x0b13"},
  "capture_file": "captura.jsonl",
  "capture_sha256": "optional-64-hex",
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

| Campo | Regra |
| --- | --- |
| `manifest_version` | inteiro `== 1`; outro valor ⇒ rejeição com a lista de versões suportadas |
| `device` | obrigatório: `device_id` (string não vazia, igual ao `device_id` de **todos** os frames), `name` (1–200), `vid`/`pid` (`^0x[0-9a-fA-F]{4}$`, mesma regra de `domain/profile.py`); opcionais `guid`, `serial` (strings) — nunca vão para o relatório |
| `capture_file` | basename (sem `/`, `\`, `..`, nem absoluto) igual ao basename do arquivo passado à CLI; divergência ⇒ exit 2 |
| `capture_sha256` | opcional, 64 hex; se presente, deve igualar o hash calculado |
| `nominal_rate_hz` | opcional, número finito `> 0` |
| `connection` | opcional: `usb`, `bluetooth`, `wireless_dongle`, `unknown` (padrão); só é registrado |
| `segments` | lista com 1 a 256 itens, **ordenada por `start_ns` crescente** |
| segmento comum | `kind ∈ {rest, circle, trigger_sweep}`; `start_ns`, `end_ns` inteiros JSON `>= 0` (não bool); `start_ns < end_ns` |
| `rest` | campos permitidos: `warmup_ns` (inteiro `>= 0`, padrão `0`, `< end_ns - start_ns`) |
| `circle` | obrigatórios: `stick ∈ {left,right}`, `direction ∈ {cw,ccw}` |
| `trigger_sweep` | obrigatório: `trigger ∈ {left,right}` |
| sobreposição | `end_ns_i <= start_ns_{i+1}` (encostar é permitido) |
| dentro da captura | `start_ns >= ts_first` e `end_ns <= ts_last + 1` |
| campos desconhecidos | rejeitados em qualquer nível, inclusive campos de outro `kind` |

Mais de um segmento por `kind`/`stick`/`trigger` é permitido (repetições dentro da mesma sessão). Frames fora de qualquer segmento são ignorados (aquecimento de 2 s não declarado, pausas). Sem manifesto não há inferência de segmentos.

### Arquivo `--thresholds`

JSON com `thresholds_version: 1`; qualquer campo omitido usa o default; campo desconhecido, tipo errado, não finito ou fora da faixa ⇒ exit 2 citando o campo. O relatório grava o conjunto efetivo completo.

```json
{
  "thresholds_version": 1,
  "drift_max": 0.02,
  "noise_rms_max": 0.005,
  "circularity_min": 0.90,
  "trigger_r2_min": 0.98,
  "hysteresis_max": 0.03,
  "rate_tolerance": 0.10,
  "saturation_ratio_max": 0.30,
  "center_offset_info": 0.10,
  "deadzone": {"factor": 1.5, "stick_floor": 0.02, "trigger_floor": 0.01},
  "protocol": {
    "rest_min_duration_s": 3.0, "rest_min_frames": 150,
    "rest_hard_min_duration_s": 1.0, "rest_hard_min_frames": 10,
    "drift_block_s": 1.0, "drift_block_min_frames": 5,
    "circle_min_radius": 0.3, "circle_min_points_per_lap": 100,
    "circle_min_valid_laps_per_direction": 2, "min_half_range": 0.5,
    "trigger_arm": 0.15, "trigger_exit": 0.10, "trigger_peak_min": 0.8,
    "trigger_phase_min_points": 50, "trigger_min_valid_cycles": 3,
    "trigger_min_span": 0.5,
    "rate_gap_max_s": 0.25, "rate_min_pairs": 100
  }
}
```

Faixas aceitas: limites de qualidade `> 0` e finitos; `rate_tolerance ∈ (0,1)`; `factor ∈ [1,10]`; pisos `∈ [0,0.5]`; `trigger_exit < trigger_arm < trigger_peak_min`; contagens inteiras `>= 1`. **Constantes que não são configuráveis (fixas pela versão do schema):** percentis (tipo 7), bins de 15° (24), mediana móvel de 5, âncoras 0,05/0,95, grade de 101 pontos, blocos de percentil `0.005/0.995` do range.

Comparações: um limite máximo passa se `valor < limite`; um limite mínimo passa se `valor > limite`; a tolerância de taxa passa se `|eff - nominal| <= rate_tolerance · nominal`.

### Relatório JSON (`report_kind="calibration-metrics"`, `metrics_schema_version=1`)

Parsing estrito na leitura (campos desconhecidos rejeitados). Chaves em inglês. Esqueleto (campos adicionais além do prompt estão marcados com `+`):

```json
{
  "report_kind": "calibration-metrics",
  "metrics_schema_version": 1,
  "app_version": "0.1.0",
  "created_at": "2026-10-24T00:00:00Z",
  "device": {"name": "...", "vid": "0x045e", "pid": "0x0b13"},
  "capture": {
    "file": "captura.jsonl", "sha256": "...",
    "frames": 0, "frames_outside_segments": 0, "duration_s": 0.0,
    "connection": "unknown", "nominal_rate_hz": null,
    "effective_rate_hz": 0.0, "rate_p5_hz": 0.0, "rate_p95_hz": 0.0, "rate_pairs": 0
  },
  "normalization": {"source": "mapping", "mapping_sha256": "..."},
  "protocol": {"segments": [{"kind": "rest", "index": 0, "start_ns": 0, "end_ns": 0,
                              "effective_start_ns": 0, "frames": 0, "effective_duration_s": 0.0,
                              "stick": null, "direction": null, "trigger": null}]},
  "sticks": {"left": {}, "right": {}},
  "triggers": {"left": {}, "right": {}},
  "profile_summary": {"derived": true, "profile_id": "uuid-or-null", "sticks": {}, "triggers": {}},
  "quality": {"status": "pass", "findings": []},
  "thresholds": {},
  "notes": ""
}
```

`stick.<side>`: `axes`, `center`, `center_segment_max_shift`, `rest{frames, duration_s, valid_blocks, drift, noise_rms{x,y,xy}, noise_p2p{x,y}, noise_radius{max,p99}, jitter{mean,p99,max}}`, `range{min,max,span,observed_min,observed_max,symmetry}`, `circle{valid_laps{cw,ccw}, rejected_laps, circularity{median,worst}, mean_radius{median,worst}, saturation_ratio}`, `deadzone_suggested{mode,value,basis_p99_calibrated}`, `raw{<canal>{...}}`. `trigger.<side>`: `input`, `rest`, `noise_rms`, `noise_p2p`, `noise_p99`, `max`, `span`, `max_values[]`, `max_dispersion`, `cycles{detected,valid}`, `shape_basis`, `linearity_r2{median,worst}`, `linearity_max_error{median,worst}`, `hysteresis{median,worst}`, `saturation_ratio`, `deadzone_suggested{value}`, `raw{...}`. Métrica não calculável é `null` e acompanhada de achado.

**Achado:** `{"code", "severity", "message" (PT-BR), "metric" (caminho JSON ou null), "value" (número ou null), "threshold" (+, número ou null), "strict_blocking" (+, bool)}`. Ordem estável: severidade (`error`, `warning`, `info`), depois `code`, depois `metric`.

**`quality.status`:** `fail` se existe achado `error`; senão `warn` se existe `warning`; senão `pass`. `info` não altera o status.

**Markdown:** derivado só do JSON, na estrutura da skill `calibration-metrics` (Dispositivo, Captura, Sticks, Triggers, Riscos e observações), sem recalcular nada.

### Catálogo de achados

| Código | Condição | Severidade | `--strict` bloqueia |
| --- | --- | --- | --- |
| `MISSING_REST_SEGMENT` | nenhum `rest`; **um único achado** com `metric="protocol.segments"` (não um por stick/trigger) | error | sim |
| `REST_TOO_SHORT` | emitido em três escopos independentes, cada um com seu `metric`: (a) global, duração efetiva agrupada `< rest_min_duration_s` (`protocol.rest.effective_duration_s`; error se `< rest_hard_min_duration_s`); (b) por canal, frames efetivos do stick/trigger `< rest_min_frames` (`<raiz>.rest.frames`; error se `< rest_hard_min_frames`), porque o evdev só emite frames em mudança e canais diferem; (c) por stick, `drift = null` por menos de 2 blocos (`<raiz>.rest.drift`, warning) | warning / error | sim |
| `MISSING_CIRCLE_SEGMENT` | stick sem `circle` (error, `metric` = raiz do stick, que cobre `sticks.<lado>.range.*` e `.circle.*`); só uma direção (warning, `metric` = `sticks.<lado>.circle.valid_laps.<direção>`, e nenhum outro achado de volta para essa direção) | error / warning | sim |
| `INSUFFICIENT_CIRCLE_POINTS` | volta com `< circle_min_points_per_lap` frames ou bin com `< 2` frames; só emitido quando o centro foi medido (sem `rest` as voltas não são analisadas) | warning | sim |
| `INSUFFICIENT_CIRCLE_LAPS` | direção com segmento e `< circle_min_valid_laps_per_direction` voltas válidas (warning, só se o stick tem ao menos 1 volta válida); stick com 0 voltas válidas (error). Só emitido quando o centro foi medido: sem `rest` o achado correto é `MISSING_REST_SEGMENT` | warning / error | sim |
| `CIRCLE_DIRECTION_INCONSISTENT` | sinal observado incoerente com o rótulo | warning | sim |
| `MISSING_TRIGGER_SEGMENT` | trigger sem `trigger_sweep` | error | sim |
| `INSUFFICIENT_TRIGGER_CYCLES` | ciclos válidos `< trigger_min_valid_cycles` (warning); 0 (error). Só emitido quando o `rest` do trigger foi medido (sem repouso os ciclos não são analisados) | warning / error | sim |
| `AXIS_MISSING` | frames de segmento sem um eixo do stick/trigger: `<= 5%` (warning); `> 5%` ou nenhum frame válido (error) | warning / error | sim |
| `DEGENERATE_RANGE` | semi-range `< min_half_range` em qualquer lado, ou `span` do trigger `< trigger_min_span`. No trigger, com `trigger_peak_min = 0,8` e `rest >= 0`, `span < 0,5` exige `rest > 0,3` (mapping com `rest` baixo demais) ou `--thresholds` com `trigger_peak_min` menor que `trigger_min_span + rest`; o teste usa a segunda via | error | sim |
| `CENTER_OUTSIDE_RANGE` | `c <= range_min` ou `c >= range_max` (viola `domain/profile.py:137`) | error | sim |
| `DEADZONE_CLAMPED` | deadzone teria passado de `0.95` | warning | sim |
| `HIGH_DRIFT` | `drift >= drift_max` | warning | sim |
| `HIGH_NOISE` | `noise_rms.xy >= noise_rms_max` (stick) ou `noise_rms >= noise_rms_max` (trigger) | warning | sim |
| `MAPPING_RANGE_EXCEEDED` | `out_of_range_ratio > 0` | warning | sim |
| `DUPLICATE_TIMESTAMP` | `Δt = 0` em algum par | warning | sim |
| `RATE_OUT_OF_TOLERANCE` | taxa efetiva fora de `nominal ± rate_tolerance` | warning | sim |
| `LOW_CIRCULARITY` | `circularity.median <= circularity_min` | warning | não (gate quadrado/octogonal é mecânico) |
| `SATURATION_HIGH` | `saturation_ratio >= saturation_ratio_max` | warning | não (gate quadrado satura por construção) |
| `LOW_TRIGGER_R2` | `linearity_r2.median <= trigger_r2_min` | info | não |
| `HIGH_HYSTERESIS` | `hysteresis.median >= hysteresis_max` | info | não |
| `CENTER_FAR_FROM_MAPPING` | `max(abs(c_x), abs(c_y)) > center_offset_info` (centro do mapping provavelmente errado ou stick desgastado) | info | não |
| `UNMAPPED_CHANNEL_IGNORED` | canal do JSONL ausente no mapping | info | não |
| `NOMINAL_RATE_UNKNOWN` / `RATE_UNAVAILABLE` | sem taxa nominal / `rate_pairs` insuficiente | info | não |

`NON_MONOTONIC_TIME` e os demais erros de entrada (captura, manifesto, thresholds, mapping inválidos) **não** produzem relatório: saem com exit 2 e a mensagem começa com `[CÓDIGO]`.

**Regra de `--strict` e exit codes.** Exit 4 se `--strict` e houver achado `error` ou `warning` com `strict_blocking=true`. Sem `--strict`, exit 0 mesmo com `status=fail` (o relatório documenta). Com `--save-profile`, se o perfil não puder ser derivado (há `error`), o relatório é escrito, nenhum perfil é gravado e o exit é 4 (extensão ao prompt, ver P2). Em `--strict`, nenhum perfil é gravado quando o exit é 4.

## Algoritmo (orquestração)

1. Ler mapping, manifesto, thresholds, captura (estrita); validar tudo (erros ⇒ exit 2).
2. Normalizar cada frame com o mapping (`normalize_frame`), apenas nos canais mapeados.
3. Atribuir frames aos segmentos pelas janelas semiabertas; aplicar `warmup_ns` nos `rest`.
4. Calcular, nesta ordem: centro ⇒ ruído/drift/jitter ⇒ range ⇒ voltas/circularidade ⇒ deadzone (usa centro e range) ⇒ triggers (rest ⇒ ciclos ⇒ forma ⇒ deadzone) ⇒ captura.
5. Avaliar thresholds e montar achados; derivar `quality.status`.
6. Derivar o perfil (abaixo) se não houver `error`.

### Derivação do perfil v1 (D10)

Todos os valores em `round(x, 6)` antes de construir (e portanto validar) o perfil.

| Campo | Valor |
| --- | --- |
| `sticks.<side>.center` | `center` (mediana do repouso) |
| `sticks.<side>.range.min/max` | `P_0.005` / `P_0.995` por eixo sobre os `circle` do stick |
| `sticks.<side>.deadzone` | `{mode: "cut", value: dz}` |
| `sticks.<side>.curve` / `invert` | `{type: "linear"}` / `[false, false]` |
| `triggers.<side>.rest` / `max` | `rest` / mediana de `m_k` |
| `triggers.<side>.deadzone` | `dz` do trigger |
| `triggers.<side>.curve` / `invert` | `{type: "linear"}` / `false` |
| `device` | do manifesto (`name`, `vid`, `pid`, `guid`, `serial`) |
| `notes` | `"zonepad measure; captura=<basename>; sha256=<12 primeiros hex>; metrics_schema_version=1; status=<s>; avisos=<códigos de warning/error, ordenados, separados por vírgula>"`, truncado em 2000 caracteres com `…` |

Por que `P_0.005/P_0.995` e não `min/max`: um frame espúrio num extremo faria o runtime reescalar toda a saída. Em um círculo uniformemente amostrado, o viés do percentil sobre o extremo de `r·cos θ` é `~1,2e-4·r` (cálculo: `arccos(c) = 0.5%·π`), desprezível. O `observed_min/max` fica no relatório como pior caso.

Falhas de derivação (sem epsilon, ver RF5): `CENTER_OUTSIDE_RANGE`, `DEGENERATE_RANGE`, trigger com `rest >= max`, qualquer `error` pendente. A mensagem diz qual métrica e qual ação (por exemplo, "refaça o círculo do stick esquerdo contornando toda a borda do gate").

## Protocolo de captura

O protocolo materializa o da skill `calibration-metrics`; a sessão dura ~85 s. Uma sessão = uma conexão = um par captura+manifesto.

| Passo | Ação do usuário | Duração | Segmento declarado | Mínimos (por padrão) |
| --- | --- | --- | --- | --- |
| 0 Aquecimento | Controle conectado, sem tocar | 2 s | nenhum (frames fora de segmento) | — |
| 1 Repouso | Sem tocar em nada | 5 s | `rest`, `warmup_ns=1e9` | efetivo `>= 3 s` e `>= 150` frames; duro: `>= 1 s` e `>= 10` frames |
| 2 Círculos | Por stick: 3 voltas horárias na borda do gate (~2 s cada), pausa, 3 anti-horárias | ~6 s por direção | um `circle` por stick e direção | `>= 2` voltas válidas por direção; volta válida `>= 100` frames e 24 bins com `>= 2` frames |
| 3 Triggers | Por trigger: 5 ciclos de [0,5 s parado no repouso, ~2 s subindo, 0,5 s parado no fundo, ~2 s descendo] | ~25 s | um `trigger_sweep` por trigger | `>= 3` ciclos válidos (pico `>= 0,8`; `>= 50` frames por fase) |
| 4 Botões | — | — | — | fora do v1 |
| 5 Repetição | Repita a sessão em outra captura (idealmente reconectando) | — | — | comparação entre sessões fora do v1 |
| 6 Registro | Salve JSONL raw + manifesto | — | — | `timestamp_ns` monotônico; valores raw preservados |

Notas: (a) o stick que não está sendo testado deve ficar solto; seus frames dentro do `circle` do outro stick são ignorados. (b) Um segundo `rest` ao final é recomendado para evidenciar deriva e é suportado (`center_segment_max_shift`). (c) Os mínimos de 3 s/150 frames para o repouso cobrem 50 Hz × 3 s; `150` dá `~1,5` amostras acima do `P_0.99` e é um **default a validar**.

### Mapeamento violação ⇒ achado

Cada linha da coluna "Mínimos" acima mapeia para um código do catálogo: repouso ⇒ `MISSING_REST_SEGMENT` / `REST_TOO_SHORT`; volta ⇒ `INSUFFICIENT_CIRCLE_POINTS`; voltas por direção ⇒ `INSUFFICIENT_CIRCLE_LAPS`; segmento ausente ⇒ `MISSING_CIRCLE_SEGMENT` / `MISSING_TRIGGER_SEGMENT`; ciclos ⇒ `INSUFFICIENT_TRIGGER_CYCLES`; eixo sem dados ⇒ `AXIS_MISSING`.

## Decisões D1–D10

| ID | Decisão fechada | Mudança sobre a recomendação inicial | Dono |
| --- | --- | --- | --- |
| D1 | Manifesto sidecar `manifest_version=1`, intervalos `[start_ns,end_ns)`, JSONL inalterado | **Adiciona** `device.device_id` (sem ele, "dispositivo coerente com os frames" é vazio: o frame só carrega `device_id`, C1), `capture_sha256`, `nominal_rate_hz`, `connection`; `warmup_ns` só em `rest`; segmentos ordenados | `controller-hardware` |
| D2 | Camada normalizada (com o mapping) + diagnóstico `raw.*` | **Exige `--mapping`** na CLI: o perfil só é válido no espaço normalizado pelo mapping do runtime (C2); sem ele a spec não tem como normalizar | `controller-hardware` |
| D3 | Cálculo em `domain/metrics.py` puro; orquestração em `application/measure.py`; IO fora | Sem mudança de semântica; a spec só impõe stdlib (C9) e funções puras sobre sequências já normalizadas | `python-engineer` |
| D4 | Relatório separado, perfil v1 intacto | Sem mudança. Consequência: pior caso, drift e ruído não são persistidos no perfil; só entram em `notes` e no relatório | `controller-hardware` + `python-engineer` |
| D5 | `dz = clamp(max(1.5·P_0.99(ρ), 0.02), 0, 0.95)`, radial, `cut`, no **espaço calibrado**; trigger em fração do span, piso `0.01` | Fecha fator e piso; define a base em espaço calibrado (o prompt dizia `noise_radius` normalizado); usa `P_0.99`, não o máximo | `controller-hardware` |
| D6 | Mínimos da tabela do protocolo, sempre via achado, nunca exceção silenciosa | Fecha os números; introduz nível duro (error) além do mínimo (warning) | `controller-hardware` |
| D7 | `zonepad measure` | Sem mudança de nome; argumentos ganham `--mapping` obrigatório | `python-engineer` |
| D8 | `effective_rate = 1/mean(Δt)`; p5/p95 de `{1/Δt}`; `Δt < 0` ⇒ exit 2 | **População restrita a pares dentro de `circle` com `Δt <= 0,25 s`**; nominal opcional vindo do manifesto; `Δt = 0` vira warning, não erro | `controller-hardware` |
| D9 | Relógio e `profile_id` injetados; cálculo sem `datetime.now()` | Acrescenta arredondamento a 6 casas, `sort_keys` e hashes de entrada como parte do contrato de determinismo | `python-engineer` |
| D10 | Perfil com `linear`, `invert=false`, centro por mediana, range por `P_0.005/P_0.995` | Sem mudança de semântica; o range deixa de usar `min/max` crus | `controller-hardware` |
| D11 (nova) | `linearity_*` e `hysteresis` são proxies temporais, com achados `info` | O prompt trata-os como thresholds de aceite; sem sensor de curso eles medem também o dedo (ver limitação) | `controller-hardware` |

## Impacto por camada

- **Domínio** (`domain/metrics.py`, novo): funções puras, dataclasses `frozen, slots`, entrada = sequências já normalizadas + timestamps + parâmetros; nenhum IO. `domain/profile.py` e `domain/calibration.py` não mudam.
- **Aplicação** (`application/measure.py`, novo; `build_profile_from_metrics` em `application/calibration.py` ou módulo equivalente): orquestra segmentação, normalização com `normalize_frame`, métricas, achados e derivação do perfil. `build_profile` legado fica como está (`:17-72`); ele usa média/`min`/`max` e epsilon, semântica diferente, e deve ser marcado como legado pelo `python-engineer`.
- **Infraestrutura:** leitor estrito de captura (C1), leitor de manifesto e de thresholds, escrita de relatório. `JsonProfileStore` é reutilizado sem mudança (C10).
- **Interface (CLI):** `zonepad measure CAPTURE --manifest M --mapping MAP [--report] [--report-md] [--save-profile DIR] [--thresholds T] [--strict]`; sem lógica de calibração; stdout recebe o JSON quando não há `--report`.
- **Perfil:** `schema_version=1` inalterado; sem campo novo. Relatório versionado à parte; não é necessário `schema_version=2`.

## Impacto em hardware/dispositivos

Só entram quirks que alteram a medição. Rótulos: **[F]** fato nesta spec (código local), **[I]** inferência a partir de conhecimento do domínio, **[L]** lacuna.

| Dispositivo / camada | Efeito na medição | Status |
| --- | --- | --- |
| Linux evdev (todos) | Timestamp = instante da leitura (C8), não do hardware; frames só em mudança de valor; o kernel pode aplicar `fuzz`/`flat` do driver (via `EVIOCGABS`) que filtram ruído abaixo de `fuzz` | timestamp **[F]**; filtro de repouso e `fuzz` **[I/L]**: confirmar com `evtest` e `EVIOCGABS` por dispositivo |
| Xbox (XInput-class) | Sticks em 16 bits tendem a dar resolução fina; triggers 8–10 bits conforme driver/modo | **[I/L]**: ranges devem vir do mapping medido, não da spec |
| DualShock/DualSense | Sticks de 8 bits ⇒ `lsb_normalized ≈ 0,0078`; ±1 LSB de oscilação dá `noise_rms ≈ 0,0078 > 0,005` e `HIGH_NOISE` legítimo; o piso `0.02` equivale a ~2,5 LSB. Gatilhos adaptativos do DualSense podem alterar o curso e, portanto, a forma do trigger | **[I/L]**: confirmar com captura; o campo `raw.*.lsb_normalized` expõe a resolução real |
| Switch Pro | ZL/ZR costumam ser botões digitais, sem canal analógico `lt/rt`; `measure` v1 falha com `MISSING_TRIGGER_SEGMENT` e não gera perfil, pois o perfil exige os dois triggers (`domain/profile.py:292`) | digitais **[I/L]**; limite do perfil **[F]**; ver P3 |
| 8BitDo | Resolução, mapa de eixos e presença de trigger analógico variam por modo (XInput/DInput/Switch) e firmware | **[L]**: um mapping por modo; sem generalização |
| HID genérico | Sem mapping medido, nada é assumido; o `--mapping` é obrigatório | **[F]** (ADR 0003) |
| Steam Input / camadas | Podem criar dispositivo virtual com filtros; meça no nó físico e registre | **[I]** (skill `controller-protocols`) |
| Bluetooth | Latência e jitter maiores; `connection="bluetooth"` fica registrada; a taxa deve ser comparada só com `nominal_rate_hz` da mesma conexão | **[I]** |

## Plano de testes

Sem hardware, sem `/dev/input`, sem `sleep`. Fixtures sintéticas geradas em código; mapping de teste com `minimum=-32768, center=0, maximum=32767` e `rest=0, maximum=255` (inteiros raw, convertidos pelo pipeline real). Tolerância numérica `1e-9`, exceto quando indicado.

| Caso | Entrada | Esperado |
| --- | --- | --- |
| Centro e drift | repouso constante em `(0.1, -0.1)` (≥ 150 frames, 4 s) | `center = (0.1, -0.1)`, `drift = 0`, `noise_* = 0` |
| Ruído | `x` alternando `±0.01` com contagem **par**, `y = 0` | `center.x = 0`, `noise_rms.xy = 0.01`, `noise_p2p.x = 0.02`, `noise_radius.max = 0.01` |
| Deadzone | ruído de raio conhecido `ρ_99`, semi-range 1 | `dz = max(1.5·ρ_99, 0.02)`; com ruído zero, `dz = 0.02` |
| Deadzone com range curto | semi-range 0.8, ruído normalizado 0.04 | `ρ` cresce por `1/0.8` antes do fator |
| Drift de rampa | repouso efetivo de 4 s (4 blocos de 1 s) com rampa linear de amplitude `D = 0.06` em `x` | `drift = 3D/8 ≈ 0.0225 >= 0.02` (HIGH_DRIFT); `noise_rms.xy ≈ 0.29·D ≈ 0.017` (HIGH_NOISE também dispara: a deriva entra no ruído). Com `D = 0.03`, `drift ≈ 0.0113` e não dispara |
| Drift ignora ruído rápido | repouso a 100 Hz (blocos de 100 frames, contagem par) com `x` alternando `±0.01` a cada frame, 4 s | `drift = 0` (a mediana de contagem par fica em 0), `noise_rms.xy = 0.01`. Com contagem ímpar (125 Hz, 125 frames por bloco) a mediana de um ruído bimodal cai num dos dois modos e `drift = 0.01` (medido em revisão): num stick de 8 bits que oscila entre dois LSB, `drift` pode chegar a ~1 LSB (0,0078), abaixo de `drift_max = 0.02` |
| Circularidade | 1000 pontos por volta, raio 0.9, 1 volta mais 2 passos de fechamento (`Θ >= 2π`) | `valid_laps = 1`, `circularity = 1`, `mean_radius = 0.9`. Com exatamente 1000 pontos em `[0, 2π)` o resultado é `valid_laps = 0` (travar com um teste) |
| Gate elíptico | semi-eixos 0.9 e 0.45, amostragem uniforme em ângulo polar | `circularity ≈ 0.50` (tolerância 0.02; o método de bins dá ~0.504) |
| Voltas | 3 voltas cw + 3 ccw | `valid_laps = {cw: 3, ccw: 3}`; rótulos trocados ⇒ `CIRCLE_DIRECTION_INCONSISTENT` |
| Volta pobre | 80 pontos por volta | `INSUFFICIENT_CIRCLE_POINTS` e volta fora da circularidade |
| Range robusto | círculo + 1 frame espúrio em `x = 1.0` | `range.max.x` ignora o espúrio; `observed_max.x = 1.0` |
| Linearidade | rampa linear 0→1 e 1→0, 5 ciclos | `R² = 1`, erro `~0` |
| Histerese | subida `y = x`; descida `y = x + 0.05·sin(πx)` (125 Hz, 2 s por rampa) | `hysteresis ≈ 0.042` (medido 0.04197, tolerância 0.002). O valor é `0.05·sin(πx*) - δ` com `δ ≈ 0.007`, o deslocamento da curva de descida nas âncoras 0,05/0,95 que a re-registro das fases apaga: a fórmula, e não um defeito, explica 0,042 em vez de 0,05 |
| Histerese: offset vertical puro | subida `y = x`; descida `y = x - 0.05` (clipada em 0) | resultado documentado: ≈ 0 (limitação de princípio, ver D11); o teste existe para travar esse comportamento |
| Ciclos de trigger | pico `0.7` | ciclo inválido; 0 válidos ⇒ `INSUFFICIENT_TRIGGER_CYCLES` (error) |
| Trigger com repouso alto | repouso medido `0.2` (mapping com `rest` baixo), 3 ciclos até `1.0` | ciclos detectados e válidos (limiares relativos ao repouso); `rest = 0.2` no perfil |
| Trigger de curso curto | `--thresholds` com `trigger_peak_min = 0.45`, pico `0.45` | `DEGENERATE_RANGE` (error) por `span < 0.5` |
| Sem repouso | nenhum `rest` | um único `MISSING_REST_SEGMENT` (`metric="protocol.segments"`); nenhum `INSUFFICIENT_CIRCLE_LAPS` nem `INSUFFICIENT_TRIGGER_CYCLES` |
| Simetria com centro além do máximo | `c > max` num eixo | `range.symmetry[eixo] = null` e `CENTER_OUTSIDE_RANGE` |
| Captura grande | arquivo de captura > 32 MiB | exit 2, `[INVALID_CAPTURE]` |
| Taxa | timestamps a 1 kHz dentro de `circle` | `effective_rate_hz = 1000`, `rate_p5 = rate_p95 = 1000` |
| Taxa com pausa | par com `Δt = 0.5 s` | par excluído da população |
| Timestamp decrescente | `ts` cai na linha 12 | exit 2, `[NON_MONOTONIC_TIME]`, linha 12 |
| Timestamp duplicado | `ts_i = ts_{i+1}` | `DUPLICATE_TIMESTAMP`, sem exceção, par fora da taxa |
| Não finito | `NaN`/`Infinity` no JSONL ou no thresholds | exit 2; relatório nunca contém `NaN` |
| Tipo inválido | `timestamp_ns: 1.5`, eixo float, bool | exit 2 com linha |
| Captura vazia | arquivo vazio | exit 2 |
| Manifesto inválido | versão errada, sobreposição, fora de ordem, `kind` desconhecido, campo extra, campo de outro `kind`, fora da captura, `device_id` divergente, `capture_file` divergente | exit 2 por caso, mensagem com o campo |
| Segmento curto | repouso efetivo 2 s | `REST_TOO_SHORT` (warning); sem `--strict` o perfil é gravado; com `--strict` exit 4 sem perfil |
| Sem círculo | stick sem `circle` | `MISSING_CIRCLE_SEGMENT` (error), sem perfil, exit 4 se `--save-profile` |
| Centro fora do range | círculo que não cruza `c` num lado | `CENTER_OUTSIDE_RANGE`; sem perfil |
| Mapping estreito | raw acima de `maximum` | `MAPPING_RANGE_EXCEEDED` |
| Canal extra | `hat` no JSONL | `UNMAPPED_CHANNEL_IGNORED` (info), sem falha |
| Perfil | métricas sintéticas válidas | `validate_profile` aprova; `range_min < center < range_max`; `rest < max`; `deadzone <= 0.95`; carrega no `JsonProfileStore` |
| Determinismo | mesma entrada, relógio e UUID fixos, duas execuções | relatório e perfil idênticos byte a byte |
| Regressão | suíte atual | inalterada e verde |

## Riscos

| Risco | Impacto | Mitigação / status |
| --- | --- | --- |
| Eventos só em mudança (evdev) deixam o repouso esparso ou vazio | `REST_TOO_SHORT` em controles muito limpos; estatísticas ponderadas por evento, não por tempo **[I]** | Mínimo por frames e por duração; o capturador do wizard deve registrar frames periódicos com hold (P6) |
| `linearity_*`/`hysteresis` por proxy de tempo | Humano reprova hardware bom; hardware ruim passa | Achados `info`, `shape_basis` explícito; revalidar com pacing guiado (P4) |
| Thresholds sem amostra real | Falso aprovado/reprovado | Todos os números marcados *default a validar*; relatório registra o efetivo; `controller-hardware` assina após smoke com captura real (etapa 9) |
| Deriva térmica não coberta | Repouso de 4 s não detecta deriva de minutos | Segundo `rest` ao final; `center_segment_max_shift`; limitação declarada |
| Deadzone de firmware escondida | Deadzone de software soma-se a ela; ruído medido ~0 | Piso `0.02`; sonda de deadzone fica para v2 (P5) |
| Mapping errado | Centro e range descalibrados, saturação falsa | `raw.*`, `MAPPING_RANGE_EXCEEDED`, `CENTER_FAR_FROM_MAPPING`; o `measure` não corrige o mapping |
| Resolução de 8 bits | `noise_rms` mínimo `~0,0078` > threshold | `lsb_normalized` no relatório; threshold configurável; **[I]** a validar com DualSense real |
| Segmentação manual errada | Métricas sobre a janela errada | Validação de manifesto, cobertura e `frames` por segmento no relatório |
| Gate não circular | `LOW_CIRCULARITY` é mecânico | Não bloqueia `--strict`; reporta pior caso |
| Troca de y (sinal) / `cw` vs `ccw` | Rótulo invertido | Checagem só de consistência; `invert` não é inferido (D10) |
| Captura com dados pessoais | Vazamento | Relatório só com basename, `vid/pid`, nome; `serial`/`guid` só no perfil local; anonimizar capturas antes de compartilhar |

## Critérios de aceite

- [ ] Toda métrica da seção "Modelo de dados" tem camada, unidade, janela e fórmula; os testes do plano reproduzem os números esperados com a tolerância indicada.
- [ ] Percentis usam o tipo 7; centro é mediana; o relatório traz mediana e pior caso (ou `p99`) onde a tabela pede.
- [ ] Manifesto: aceita o exemplo desta spec e rejeita cada caso da linha "Manifesto inválido" com exit 2 e campo na mensagem.
- [ ] Captura estrita: rejeita `NaN`, float em `timestamp_ns`, `device_id` misto e `ts` decrescente, citando a linha.
- [ ] Cada código do catálogo é produzido por pelo menos um teste e tem a severidade e o `strict_blocking` da tabela.
- [ ] `quality.status` segue a regra `fail`/`warn`/`pass`; `info` não o altera.
- [ ] `--strict` retorna 4 com achado `error` ou `warning` bloqueante e 0 sem `--strict`.
- [ ] O perfil derivado passa em `validate_profile`, mantém `range_min < center < range_max`, `rest < max`, deadzone em `[0,0.95]`, `curve=linear`, `invert=false`, `schema_version=1`, sem campo novo.
- [ ] Relatório e perfil são byte a byte idênticos em duas execuções com relógio e `profile_id` injetados.
- [ ] Nenhum `NaN`/`Infinity` na saída (`allow_nan=False`) e nenhuma métrica `null` sem achado.
- [ ] Smoke com captura real (etapa 9): plausibilidade dos números e assinatura dos thresholds por `controller-hardware`; se não executado, declarado como lacuna.

## Decisões do usuário (P1–P8 resolvidas)

Todas as decisões abaixo foram aprovadas conforme a coluna "Recomendação"; o texto da tabela permanece como registro das opções consideradas.

| ID | Pergunta | Opções | Recomendação |
| --- | --- | --- | --- |
| P1 | Normalização: o `measure` exige `--mapping` (diverge do CLI do prompt)? | (a) `--mapping` obrigatório, o mesmo do `run`; (b) bloco `normalization` no manifesto; (c) derivar ranges da própria captura | **(a)**: reaproveita ADR 0003 e garante o mesmo espaço do runtime; (c) é circular (mede o range que normaliza) |
| P2 | Exit 4 quando `--save-profile` é pedido e o perfil não pode ser derivado? | (a) exit 4 com relatório escrito; (b) exit 1; (c) exit 0 com aviso | **(a)** |
| P3 | Controles sem trigger analógico (Switch Pro, alguns 8BitDo)? | (a) v1 não suporta (sem perfil); (b) perfil v2 com trigger opcional (ADR + migração); (c) flag explícita para preencher `rest=0, max=1` | **(a)** em v1; abrir (b) no ADR 0004 como caminho futuro |
| P4 | Manter `linearity`/`hysteresis` como `info` (proxy)? | (a) `info`; (b) `warning` bloqueante; (c) remover do v1 | **(a)**; reavaliar após pacing guiado do prompt 03 e capturas reais |
| P5 | Sonda de deadzone de firmware (empurrão lento a partir do centro) | (a) segmento `deadzone_probe` em manifesto v2 / prompt 03; (b) adiar | **(a)**, para o wizard |
| P6 | O capturador (wizard) deve gravar frames periódicos com hold e um frame de fechamento? | (a) sim; (b) manter só eventos | **(a)**: sem isso, controles sem ruído falham em `REST_TOO_SHORT` |
| P7 | Comparação entre sessões repetidas | (a) fora do v1; (b) incluir agora | **(a)**; prompt 03 compara relatórios |
| P8 | Aprovação da tabela `strict_blocking` e dos defaults (`factor 1.5`, `floor 0.02/0.01`, mínimos de amostra) | aprovar / ajustar | Aprovar como *default a validar*; assinatura final após captura real |

## Revisão de hardware (2026-10-24, `controller-hardware`, etapas 4/6/8/11 do prompt 02)

Mudanças feitas nesta spec após a aprovação, cada uma com a evidência. Nenhuma altera P1–P8, D1–D11 nem o schema do perfil ou do relatório (salvo o item 9, que só documenta campos já emitidos).

| # | Mudança | Evidência |
| --- | --- | --- |
| 1 | RF4: `metric` de um achado nomeia o caminho ou um ancestral | `sticks.left` cobre `sticks.left.range.*` |
| 2 | RNF: captura em memória no v1, com limite de 32 MiB | `tracemalloc`: 63 012 frames, 9,4 MB de arquivo, ~70 MB residentes, pico ~100 MB |
| 3 | C8: o construtor fixa `read_monotonic`; `event_timeval` só em `object.__new__` | `evdev.py:49`, `:100`; `test_runtime_cli.py:198` |
| 4 | `range.symmetry` é `null` também quando `max - c <= 0` | reprodução: `c = 0.5`, `max ≈ 0` deu `-0.2175` |
| 5 | Drift: texto de relação com ruído corrigido; teste com `D = 0.06` | reprodução: `D = 0.03` deu `drift = 0.01127` e `noise_rms.xy = 0.00868` |
| 6 | Volta completa exige `Θ >= 2π`; limite de `cw`/`ccw` e transiente de entrada declarados | reprodução: 1000 pontos em `[0, 2π)` deu 0 voltas; espiral de 0,5 s deu `circularity.worst = 0,387` |
| 7 | Arm/exit do trigger relativos ao repouso; janela de contexto das âncoras; fase conta frames medidos | reprodução: repouso `0.2` deu 0 ciclos detectados |
| 8 | `MISSING_REST_SEGMENT` único; `INSUFFICIENT_CIRCLE_*` e `INSUFFICIENT_TRIGGER_CYCLES` só com repouso medido; escopos de `REST_TOO_SHORT` | reprodução sem `rest`: 4 × `MISSING_REST_SEGMENT` e 4 achados de volta/ciclo em cascata |
| 9 | Esqueleto do relatório inclui `stick`, `direction`, `trigger` nos segmentos | `report.py:184-186`, `:402-404` |
| 10 | Valor esperado da histerese 0,042 | reprodução: 0,04197; forma fechada `≈ 0,043` |
| 11 | `DEGENERATE_RANGE` do trigger: alcance e teste via `--thresholds` | `span < 0.5` com pico `>= 0.8` exige `rest > 0.3` |

## Referências

- `ai/prompts/02-calibration-metrics.md`, `ai/skills/calibration-metrics/SKILL.md`, `ai/skills/calibration-domain/SKILL.md`.
- `docs/adr/0003-mapping-json-autoritativo-para-runtime-evdev.md`.
- Código citado: `src/zonepad/infrastructure/replay.py`, `src/zonepad/domain/{input,normalization,profile,calibration}.py`, `src/zonepad/application/{calibration,runtime}.py`, `src/zonepad/infrastructure/{evdev,mapping,json_profile_store}.py`.
