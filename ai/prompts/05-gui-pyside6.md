# Prompt 05 — GUI PySide6 sobre o núcleo de calibração

- **Status:** pronto para execução em Claude Code (prioritária) e Codex (alternativa).
- **Incremento:** GUI Linux em PySide6 que consome os casos de uso existentes — seleção de dispositivo/mapping, monitor ao vivo, wizard de calibração, lista de perfis e estados de erro — sem lógica de domínio na UI.
- **Branch de implementação:** `feat/gui-pyside6`, criada a partir da `main` com este prompt mergeado.
- **Fluxos:** `/flow-design-feature` → `/flow-implement-feature` → `/flow-review-calibration`.
- **Agentes:** `python-engineer` (GUI, view-models, threading, integração, testes, docs técnicas), `controller-hardware` (semântica de visualização, instruções do wizard, qualidade/retry, plausibilidade dos números — não implementa), `prompt-engineer` (apenas `ai/` e consistência), Claude/Codex principal (orquestração, handoffs, síntese).
- **Fora deste incremento:** Windows/macOS, schema de perfil v2, fórmulas e thresholds de métricas, redesenho do wizard CLI, release/packaging (prompt 06), push/PR/merge.

## Missão

Transformar o placeholder `src/zonepad/interface/gui/__init__.py:4-13` (uma janela com `QLabel`) na GUI funcional do MVP Linux, executável por `zonepad-gui`, reutilizando o que os prompts 02–04 entregaram: motor de métricas, wizard CLI, descoberta por sysfs, identidade estável e mapping por família.

A pessoa deve conseguir, sem terminal:

1. ver os gamepads descobertos com ID estável, VID:PID, conexão, nó e status do mapping;
2. abrir o monitor e ver sticks, triggers e botões ao vivo, com unidade e escala explícitas;
3. percorrer o wizard de calibração com instruções, contagem, progresso, achados de qualidade, retry e salvamento do perfil v1;
4. listar e inspecionar perfis existentes;
5. entender e corrigir erros de dispositivo, permissão, mapping e perfil sem stack trace.

Regra estrutural: **a GUI é adaptador**. Ela não calcula métricas, não valida perfis, não normaliza nem calibra — ela chama `application/` e `infrastructure/` e apresenta resultados.

## Resultado esperado

1. Aplicação PySide6 com janela principal, navegação entre Dispositivos, Monitor, Calibração e Perfis.
2. View-models sem import de Qt, testáveis e determinísticos.
3. Adapter de descoberta/mapping sobre as portas do prompt 04, sem reimplementar sysfs, identidade ou catálogo.
4. Worker de leitura em thread própria, com sinais, coalescência de frames e fechamento previsível.
5. Widgets de stick, trigger e botões com unidades, faixas e legendas corretas.
6. Wizard GUI dirigindo `application/calibrate.step` e os mesmos `SegmentPlan` do CLI.
7. Lista e resumo de perfis com erros de perfil inválido tratados como estado de tela.
8. Matriz de estados de erro com ação de recuperação para cada caso.
9. Suíte headless (`QT_QPA_PLATFORM=offscreen`), sem hardware e sem `pytest-qt` por padrão.
10. `docs/specs/gui-v1.md`, `docs/adr/0008-*.md`, README e `ai/prompts/README.md` atualizados.

## Contexto verificado (2026-10-25, `main` em `5213f41`)

Revalide no checkout principal com working tree limpo. Os gates da seção **Validação** são a fonte de verdade.

| Verificação | Resultado |
| --- | --- |
| GUI atual | `src/zonepad/interface/gui/__init__.py:4-13` cria `QWidget` + `QLabel`, sem separação de camadas e sem casos de uso |
| Entry point | `pyproject.toml:26` — `zonepad-gui = "zonepad.interface.gui:run"` |
| Extra opcional | `pyproject.toml:16` — `gui = ["PySide6>=6.7"]`; `dev` em `:17-22` sem `pytest-qt` |
| Ambiente | `.venv` com Python 3.15.0; PySide6 **não instalado**; `pytest-qt` **ausente**; suíte com 690 testes verdes |
| Testes CI | `tests/` só com `pytest`; nenhum uso de `QT_QPA_PLATFORM` ou `offscreen` no repositório |
| State machine | `src/zonepad/application/calibrate.py:6-105` (`WizardPhase`, `WizardState`, eventos) e `step` em `:107-164`; efeitos executados pelo CLI em `interface/calibration_cli.py:254` |
| Instruções dos segmentos | `interface/calibration_cli.py:78-136` (`_plans`, 7 `SegmentPlan` em PT-BR) e `_plan_segment` em `:138-140` |
| Orquestrador CLI | `interface/calibration_cli.py:194-204` (`run_calibrate`), acoplado a TTY via `Console` |
| Descoberta | `application/discovery.py:35` (`discover_devices`), `:40` (`resolve_device_reference`), `:69` (`fragile_group`) |
| Mapping | `application/mapping_resolution.py:43` (`resolve_mapping`), `application/ports.py:143-165` (`StoredMappingRef` com `status`) |
| Hot-plug | `application/hotplug.py:30` (`PollingHotplugWatcher`) com `Clock` injetado, sem Qt |
| Leitura | `application/ports.py:25-34` (`DeviceSession.read(timeout_s)` bloqueante); `application/runtime.py:19` (`RuntimeProcessor`) |
| Captura | `application/ports.py:75-100` (`CaptureSession` com `progress: Callable[[float], None]`) |
| Qualidade | `domain/findings.py:43` (`Finding`), `domain/quality.py` (`evaluate_quality`), `STRICT_BLOCKING` em `findings.py:14-37` |
| CLI de descoberta | `interface/device_cli.py:271` (`add_device_commands`), `:555` (`run_devices`), `:683` (`_watch`) |
| Perfis | `infrastructure/json_profile_store.py` implementa `ProfileStore` (`ports.py:43-49`) |
| Guardas de arquitetura | `tests/test_architecture.py` proíbe `application/` importar `interface/` e `domain/` importar SO/IO |
| README | `README.md:232` ainda descreve a GUI como opcional sem dizer que é placeholder |

Leia antes de editar: `AGENTS.md`, `docs/specs/wizard-v1.md`, `docs/specs/metrics-v1.md`, `docs/specs/device-discovery-v1.md`, `docs/adr/0003-*.md`, `docs/adr/0004-*.md`, `docs/adr/0005-wizard-cli-calibrate.md`, `docs/adr/0006-descoberta-e-identidade-de-dispositivos.md`, `src/zonepad/application/calibrate.py`, `src/zonepad/application/ports.py`, `src/zonepad/application/discovery.py`, `src/zonepad/application/mapping_resolution.py`, `src/zonepad/application/hotplug.py`, `src/zonepad/application/runtime.py`, `src/zonepad/application/measure.py`, `src/zonepad/interface/calibration_cli.py`, `src/zonepad/interface/device_cli.py`, `src/zonepad/interface/gui/__init__.py`, `pyproject.toml` e `tests/`.

Skills aplicáveis: `python-app-architecture`, `clean-architecture`, `clean-code`, `python-quality`, `calibration-domain`, `calibration-metrics`, `evidence-based`.

## Pré-condições

1. Este prompt deve estar mergeado em `main`. Enquanto não estiver, execute no checkout principal a partir da branch que contém o prompt e registre a exceção.
2. Trabalhe **somente no checkout principal**. Proibido `git worktree`, cópia do repositório para outro diretório e edição de arquivos gerados (`AGENTS.md`, `CLAUDE.md`, `.opencode/`, `.claude/`, `.agents/`, `.codex/`).
3. Crie a branch de implementação a partir da `main`:

```bash
cd /home/costa/Workspace/zonepad
git status --porcelain        # deve estar vazio
git switch main
git pull --ff-only
git switch -c feat/gui-pyside6
```

4. Toolchain e baseline:

```bash
asdf current python        # 3.15.0; se não, pare e reporte
python --version           # Python 3.15.0
test -d .venv || (python -m venv .venv)   # ou: virtualenv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'         # baseline sem GUI
python -m pytest -q                       # 690 testes verdes antes de editar
python -m pip install -e '.[dev,gui]'     # habilita PySide6
python -c "import PySide6; print(PySide6.__version__)"
```

5. Se não existir wheel de PySide6 compatível com Python 3.15 no índice configurado, **pare**: registre a versão tentada, o erro do pip e peça decisão ao usuário (manter o extra, subir a versão mínima ou adiar a GUI). Não altere `requires-python` nem instale Qt do sistema para contornar.
6. Gates de entrada:

```bash
git status --porcelain        # vazio
git branch --show-current     # feat/gui-pyside6
git log --oneline main..HEAD  # vazio no início
```

Se qualquer gate falhar, pare e peça um checkout principal limpo.

7. Regras de git e segurança:

- Commit local permitido; push, PR, merge e rebase só com pedido explícito do usuário.
- Proibido `git stash`, `git reset`, `git checkout --`, `git restore`, `git rebase`, `git push --force` e `sudo`.
- Nenhum teste abre `/dev/input`, `/dev/uinput`, `/sys` real ou inicia display real; a CI usa `offscreen`.
- Dependência nova além de `PySide6` exige aprovação explícita do usuário e registro na spec.

## Agentes

| Agente | Executa | Não executa |
| --- | --- | --- |
| `python-engineer` | Implementa a aplicação Qt, a navegação, os view-models sem Qt, o worker de leitura e o ciclo de vida de threads, os adapters de descoberta/mapping/perfis, os widgets, o wizard GUI, a matriz de erros, os testes headless, o ADR 0008 e a documentação técnica. | Não define unidades, escalas, semântica de stick/trigger/botão, instruções de calibração nem política de retry; não altera métricas, schema de perfil ou mapping v1. |
| `controller-hardware` | Valida a semântica de visualização: unidades (`[-1,1]`, `[0,1]`, counts raw), escalas e eixos, quais canais exibir, rótulos de botões, instruções do wizard, coerência de qualidade/retry e plausibilidade dos números exibidos. Assina o parecer de hardware da GUI. | Não implementa código; não edita `src/`, `tests/`, spec ou ADR; não decide arquitetura de módulos, threading, navegação, testes ou empacotamento. |
| `prompt-engineer` | Atua apenas em `ai/` (prompts, skills, fluxos, instruções) e na consistência entre prompt, README, spec, ADR e agentes; reporta contradições. | Não implementa GUI, view-models, widgets ou testes; não assina critério de hardware nem de arquitetura. |
| Claude/Codex principal | Orquestra design → implementação → revisão, faz handoffs com contexto, resolve conflitos entre pareceres, cobra gates, valida a spec com o usuário e sintetiza o relatório final. | Não substitui o parecer de `controller-hardware`; não inventa unidade, escala ou instrução de calibração; não autoriza push/PR/merge. |

Aprovação humana (usuário): aprova `docs/specs/gui-v1.md` e o ADR 0008 **antes** de qualquer código de produção; autoriza dependência nova, acesso a hardware real e push/PR/merge.

Handoff mínimo: objetivo, contexto verificado, restrições, arquivos relevantes, saída esperada e critério de aceite. Em Claude Code, use a ferramenta **Agent** com o nome do subagente. Em Codex, use subagente ou siga o `FLOW.md` correspondente.

## Etapas e responsáveis

| # | Etapa | Executor | Revisor/apoio | Fluxo/skill | Saída | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Preflight, branch e baseline | `python-engineer` | principal | `/flow-implement-feature` (1–2) | branch `feat/gui-pyside6`, baseline pytest | tree limpo; 3.15.0; pytest verde; PySide6 importável |
| 2 | Semântica de visualização: unidades, escalas, canais, rótulos | `controller-hardware` | principal | `/flow-design-feature` + `calibration-metrics` | seção "Modelo de dados e unidades" da spec | cada número exibido tem unidade e camada declaradas |
| 3 | Instruções do wizard na GUI, achados e retry | `controller-hardware` | `python-engineer` | `/flow-design-feature` + `calibration-domain` | seção de wizard/qualidade da spec | instruções e retry coerentes com `wizard-v1.md` |
| 4 | Arquitetura GUI, view-models, threading, D1–D12 | `python-engineer` | `controller-hardware`, `prompt-engineer` | `/flow-design-feature` + `python-app-architecture` | spec `gui-v1.md` + ADR 0008 | decisões D1–D12 fechadas e sem conflito com ADRs 0002–0007 |
| 5 | **Aprovação da spec e do ADR pelo usuário** | principal | usuário | — | spec aprovada | sem aprovação, não há implementação |
| 6 | Esqueleto: app, janela, navegação, entry point, `--smoke` | `python-engineer` | principal | `/flow-implement-feature` (6) | `gui/app.py`, `gui/main_window.py` | `zonepad-gui --smoke` retorna 0 offscreen |
| 7 | View-models puros de seleção, monitor, wizard, perfis e erros | `python-engineer` | `controller-hardware` (semântica) | `/flow-implement-feature` (4) + `clean-architecture` | `gui/viewmodels/*.py` + testes | nenhum import de Qt nos view-models |
| 8 | Adapters de descoberta, mapping e perfis | `python-engineer` | `controller-hardware` | `/flow-implement-feature` (5) | adapters sobre portas do prompt 04 | zero reimplementação de sysfs/identidade/catálogo |
| 9 | Worker de leitura, sinais/slots, coalescência e shutdown | `python-engineer` | `controller-hardware` (unidades) | `/flow-implement-feature` (5) | `gui/workers.py` + fake session | UI não bloqueia; thread encerra em < 2 s |
| 10 | Widgets de stick, trigger e botões com escala e legenda | `python-engineer` | `controller-hardware` (revisão) | `/flow-implement-feature` (6) | `gui/widgets/*.py` | eixos, faixas e unidades visíveis |
| 11 | Wizard GUI sobre a state machine | `python-engineer` | `controller-hardware` (instruções/retry) | `/flow-implement-feature` (4–6) | `gui/panels/wizard.py` + testes | todas as fases e efeitos cobertos por teste |
| 12 | Lista e resumo de perfis | `python-engineer` | principal | `/flow-implement-feature` (6) | `gui/panels/profiles.py` | perfil inválido vira estado de erro, não crash |
| 13 | Matriz de estados de erro e recuperação | `python-engineer` | `controller-hardware` (mensagens de hardware) | `/flow-implement-feature` (6) | tabela de estados + testes | cada erro do escopo tem ação de recuperação |
| 14 | Acessibilidade, high-DPI e teclado | `python-engineer` | principal | `python-quality` | checklist cumprido | PT-BR, foco, ordem de tabulação, sem cor como único sinal |
| 15 | Testes headless e CI | `python-engineer` | principal | `python-quality` | suíte `offscreen` | verde sem hardware, sem display e sem flakiness |
| 16 | Spec, ADR 0008, README e `ai/` | `python-engineer` (spec/ADR/README) + `prompt-engineer` (`ai/`) | principal | `python-quality`, `prompt-design` | docs e status do prompt 05 | `sync --check` limpo se `ai/` mudou |
| 17 | Revisão final | `controller-hardware`, `python-engineer`, `prompt-engineer` | principal sintetiza | `/flow-review-calibration` | relatório com severidade e arquivo:linha | nenhum blocker |
| 18 | Encerramento | principal | usuário | — | entrega no formato de saída | critérios marcados; riscos e handoff registrados |

`controller-hardware` é obrigatório nas etapas 2, 3, 7 (revisão), 9 (unidades), 10, 11, 13 (mensagens) e 17. Sem esse parecer, o incremento não está pronto.

## Decisões que a spec deve fechar

Cada decisão tem dono. `controller-hardware` decide semântica de visualização e de calibração; `python-engineer` decide estrutura, artefatos e testabilidade. Mudar a recomendação exige justificativa registrada na spec.

| ID | Decisão | Recomendação inicial | Dono |
| --- | --- | --- | --- |
| D1 | Binding e versão de Qt | Manter `PySide6>=6.7` (sem PyQt), sem limite superior; registrar a versão instalada na spec e no ADR; um único binding no repositório; nenhum fallback para Qt do sistema | `python-engineer` |
| D2 | Biblioteca de gráficos | Widgets próprios com `QPainter` para sticks, triggers e barras; sem `pyqtgraph`, `matplotlib`, `QtCharts` ou WebEngine; justificar pela ausência de dependência extra e pelo controle de unidade/escala | `python-engineer` |
| D3 | Navegação e janela | Uma janela principal com `QStackedWidget` + barra de navegação (Dispositivos, Monitor, Calibração, Perfis); diálogos modais apenas para confirmação, erro e resultado; uma instância de app por processo | `python-engineer` |
| D4 | Threading | `QThread` + objeto worker movido para ela; `DeviceSession.read` e `CaptureSession` nunca na thread da UI; sinais carregam snapshots imutáveis; coalescência por taxa máxima (30–60 Hz) descartando frames antigos; `QTimer` para polling de hot-plug; shutdown com `requestInterruption` + `quit` + `wait(timeout)` | `python-engineer` |
| D5 | Integração com `application/calibrate` | Reutilizar `WizardState`/`Event`/`step` e os `SegmentPlan`; mover `_plans`/textos de `calibration_cli` para `application/` com testes e fazer o CLI consumir a mesma fonte; a GUI implementa o executor de efeitos; qualquer extração mantém o CLI com comportamento idêntico | `python-engineer` |
| D6 | Seleção de dispositivo e mapping | `discover_devices` + `resolve_device_reference` + `resolve_mapping`; selecionar por `StableIdentity`, nunca por `eventN`; exibir ID estável, nome, VID:PID, conexão, nó e `StoredMappingRef.status`; refresh manual e watch opcional por `QTimer`; permissão negada gera instrução sobre grupo `input`, nunca `sudo` | `python-engineer` |
| D7 | Perfis | Listar via `ProfileStore` e `infrastructure/json_profile_store.py`; resumo somente leitura (dispositivo, `created_at`, centro, ranges, deadzone, rest/max de trigger, `notes`); aplicar perfil ao runtime fica **fora** do MVP salvo justificativa aprovada | `python-engineer` |
| D8 | Testes e CI headless | View-models em `pytest` puro; testes Qt com `QT_QPA_PLATFORM=offscreen`, `QApplication` de fixture e `PySide6.QtTest.QSignalSpy`; **não** adicionar `pytest-qt` sem aprovação; `pytest.importorskip("PySide6")`; smoke `zonepad-gui --smoke`; nenhum hardware | `python-engineer` |
| D9 | Acessibilidade | Textos e mensagens em PT-BR; navegação completa por teclado com ordem de tabulação explícita; `setAccessibleName` nos controles relevantes; nenhum estado sinalizado só por cor; fontes escaláveis e suporte a high-DPI do Qt 6 | `controller-hardware` (semântica) + `python-engineer` (implementação) |
| D10 | Empacotamento do extra `gui` | Extra continua opcional; `import zonepad` e a CLI funcionam sem PySide6; falha de import no entry point gera mensagem acionável e exit `2`, não traceback; `--smoke` valida a instalação sem abrir janela visível | `python-engineer` |
| D11 | Tratamento de erros | Tabela única erro → estado de tela → ação; sem stack trace na UI; log estruturado em stderr; ações desabilitadas quando o pré-requisito falta; retry explícito e cancelamento sempre disponível | `python-engineer` |
| D12 | Limites do MVP | Linux, um dispositivo por vez, monitor somente leitura, sem uinput, sem aplicar perfil, sem temas, sem múltiplas janelas, sem 3D, sem vídeo, sem edição manual de campos do perfil | principal |

## Escopo

### 1. Arquitetura da GUI

```text
src/zonepad/interface/gui/
├── __init__.py          # run(argv) — lazy import de Qt, --smoke, exit codes
├── app.py               # QApplication, tema básico, high-DPI, composição
├── main_window.py       # janela, navegação, menu, fechamento
├── viewmodels/          # sem Qt: estado + comandos + formatação
│   ├── devices.py
│   ├── monitor.py
│   ├── wizard.py
│   ├── profiles.py
│   └── errors.py
├── adapters/            # ponte view-model ↔ casos de uso/portas
│   ├── discovery.py
│   ├── calibration.py
│   └── profiles.py
├── workers.py           # QThread/worker, sinais, coalescência, shutdown
├── widgets/             # stick, trigger, botões, medidor, legenda
└── panels/              # devices, monitor, wizard, profiles
```

- View-models expõem estado imutável e comandos; não importam `PySide6`, `os` ou `evdev`.
- Views observam view-models por sinais do adapter; adapter traduz view-model → sinais Qt.
- Nenhum widget chama `open()`, `read()`, `load_device_mapping` ou `evaluate_quality` diretamente.
- Composição na borda (`app.py`), sem service locator global e sem singleton mutável.
- `run(argv: Sequence[str] | None = None) -> int` mantém compatibilidade com o entry point e aceita `--help`, `--version` e `--smoke`.

### 2. Seleção de dispositivo e mapping

- Painel Dispositivos lista `snapshot.gamepads` com ID estável, nome, VID:PID, conexão, nó, status do mapping (`saved`/`provisional`/`edited`/`invalid`) e avisos de identidade frágil.
- Ações: atualizar (novo `discover_devices`), ativar watch (polling por `QTimer` com intervalo validado por `validate_poll_interval`), selecionar, abrir monitor, iniciar wizard.
- Seleção guarda `StableIdentity`; `eventN` aparece só como diagnóstico.
- Mapping ausente ou inválido não bloqueia a listagem; bloqueia apenas o início do wizard, com mensagem e comando equivalente (`zonepad mapping draft --device <id>`).
- Duplicados frágeis exigem confirmação explícita antes de iniciar o wizard.
- A GUI não grava mapping draft neste incremento; se a spec incluir, precisa de decisão e teste dedicados.

### 3. Monitor ao vivo

- Sticks em plano cartesiano com eixos rotulados `x`/`y`, faixa `[-1, 1]`, marca de centro e deadzone sugerida quando disponível.
- Triggers em barra horizontal ou vertical com faixa `[0, 1]` e marca de repouso.
- Botões com nome semântico quando o mapping/catálogo permitir e código (`BTN_SOUTH`) como fallback.
- Cada painel declara a camada exibida: **normalizado** (padrão) e/ou **calibrado** quando houver perfil carregado. Raw só quando a spec justificar, sempre rotulado em counts.
- Atualização por sinais com coalescência; a UI nunca lê o dispositivo e nunca usa `sleep`.
- Taxa efetiva exibida em texto (Hz medido) para o usuário perceber queda de desempenho.
- Desconexão durante o monitor vira estado de erro com ação "voltar à seleção".

### 4. Wizard de calibração

- Reutiliza `WizardPhase`, `Event` e `step` (`application/calibrate.py:107`); os `SegmentPlan` e textos de instrução hoje em `calibration_cli._plans` (`:78-136`) devem ser movidos para um módulo compartilhado em `application/` com testes, e o CLI passa a consumir essa fonte — a GUI não importa símbolo privado de `calibration_cli` nem duplica texto.
- Telas: instrução do segmento, contagem regressiva, gravação com progresso e tempo restante, resultado com achados (`Finding` já ordenados por `sort_findings`) e decisão de retry/salvar.
- Retry segue a política de `wizard-v1.md` e `STRICT_BLOCKING`; a GUI não inventa severidade nem cria novo código de achado.
- Progresso vem de `CaptureSession`/`Clock` injetados, não de `sleep` na thread da UI.
- Cancelamento em qualquer fase executa o efeito `abort_capture`, preserva artefatos parciais e retorna ao painel com resumo.
- Salvamento usa `ProfileStore`; sucesso mostra `profile_id` e próximo comando equivalente.
- Se a orquestração atual do CLI não for reutilizável sem TTY, extraia o mínimo para `application/` com testes e mantenha o CLI equivalente; registre no ADR.

### 5. Perfis

- Lista com `profile_id`, nome do dispositivo, VID:PID, `created_at` e resumo de calibração.
- Detalhe somente leitura com centros, ranges, deadzone, rest/max e `notes`.
- Perfil inválido ou ilegível aparece com motivo e não derruba a lista.
- Sem edição, exclusão ou aplicação ao runtime neste incremento.

### 6. Estados de erro

| Situação | Estado na UI | Ação oferecida |
| --- | --- | --- |
| PySide6 ausente | mensagem no terminal, exit `2` | instrução `python -m pip install -e '.[gui]'` |
| Nenhum gamepad descoberto | estado vazio no painel | "atualizar", `--all` como diagnóstico na CLI |
| Dispositivo desconectado | banner + painel bloqueado | voltar à seleção, atualizar |
| Sem permissão em `/dev/input` | mensagem acionável | explicar grupo `input`; nunca `sudo` |
| Mapping ausente | aviso no item | comando `mapping draft` sugerido |
| Mapping inválido | erro por campo | reabrir `mapping validate` na CLI |
| Perfil inválido | erro na lista/detalhe | ignorar item, mostrar caminho |
| Falha de captura no wizard | fase `FAILED` | retry quando permitido, senão sair com resumo |
| Qt sem display | falha controlada | mensagem sugerindo `QT_QPA_PLATFORM=offscreen` apenas para teste |

- Toda mensagem em PT-BR, com causa e próximo passo; sem stack trace e sem caminho absoluto de usuário.

### 7. Ciclo de vida, threading e recursos

- Um worker de leitura por sessão aberta; encerrar antes de abrir outra.
- Fechar janela: parar timers, interromper worker, fechar `DeviceSession`, aguardar `wait()` com timeout e registrar se não encerrou.
- Nenhum `QThread` órfão em teste; fixture de `QApplication` garante `processEvents` e limpeza.
- Exceções em worker são convertidas em sinal de erro, nunca propagadas para a thread da UI.
- Sinais carregam tipos imutáveis (`frozen=True`) para evitar corrida.

### 8. Acessibilidade e ergonomia

- Todos os controles alcançáveis por teclado; ordem de tabulação revisada manualmente.
- Atalhos documentados (`Ctrl+R` atualizar, `Esc` cancelar) sem conflitar com o wizard.
- Nenhum texto cortado em fonte ampliada; layout com `QSizePolicy` e sem tamanho fixo em pixels.
- Estados com texto além de cor; contraste legível no tema claro padrão.

### 9. Testes e CI

- View-models: `pytest` puro, com fakes de dispositivo, captura, relógio e store (reutilize `tests/discovery_fakes.py`, `tests/cli_support.py`, `tests/sysfs_builder.py`).
- Qt: `QT_QPA_PLATFORM=offscreen` definido no `conftest.py` antes de importar Qt; fixture de `QApplication` única por sessão; `QSignalSpy` para sinais; sem `sleep` real.
- Teste de importação: `import zonepad` e `zonepad.interface.cli` funcionam sem PySide6 instalado.
- Teste de arquitetura: nenhum módulo de `gui/viewmodels/` importa `PySide6`; nenhum módulo de `interface/gui/adapters/` duplica lógica de descoberta.
- Smoke: `zonepad-gui --smoke` cria a janela principal offscreen, processa eventos e retorna `0`; teste dedicado em `tests/test_gui_smoke.py`.
- Nenhum teste abre dispositivo real; hardware só em smoke manual autorizado.

### 10. Documentação

- `docs/specs/gui-v1.md`: problema, usuário, escopo, arquitetura de camadas, view-models, threading, unidades exibidas, telas, matriz de erros, plano de testes, riscos e D1–D12.
- `docs/adr/0008-gui-pyside6-como-adaptador.md`: contrato público (`zonepad-gui`, `--smoke`), separação view-model/adapter/view, escolha de QPainter, política de threading e limites do MVP. Confirme que 0008 é o próximo número livre.
- `README.md`: instalação do extra `gui`, captura de tela textual das telas, fluxo recomendado `devices` → monitor → `calibrate` → perfil, limitações (Linux, um dispositivo, sem aplicar perfil) e remoção da frase de placeholder.
- `ai/prompts/README.md`: status do prompt 05 e do 06.

## Fora de escopo

- Windows, macOS, Wayland-específico ou suporte a outros toolkits além de Qt 6.
- Mudanças em domínio, fórmulas, thresholds, `docs/specs/metrics-v1.md`, schema de perfil v1/v2 ou mapping v1.
- Redesenhar o wizard CLI, o protocolo de captura ou a política de retry.
- Descoberta automática além do que o prompt 04 entregou; inclusão de novos backends.
- Emulação, `uinput`, remapeamento global, aplicar perfil ao runtime, edição/exclusão de perfis.
- Temas avançados, animações elaboradas, visualização 3D, vídeo, streaming ou gravação de tela.
- Release, packaging, cobertura e CI de release (prompt 06).
- Push, PR, merge ou rebase.

## Critérios de aceite

- [ ] `import zonepad` e `zonepad --help` funcionam em ambiente sem PySide6.
- [ ] `zonepad-gui` sem PySide6 imprime mensagem acionável em PT-BR e retorna `2`, sem traceback.
- [ ] `zonepad-gui --smoke` monta a janela principal com `QT_QPA_PLATFORM=offscreen` e retorna `0`.
- [ ] A janela principal oferece Dispositivos, Monitor, Calibração e Perfis, navegáveis por teclado.
- [ ] Nenhum arquivo em `gui/viewmodels/` importa `PySide6`, `os`, `evdev` ou `subprocess`.
- [ ] A seleção de dispositivo usa ID estável e exibe VID:PID, conexão, nó e status do mapping.
- [ ] Mapping ausente ou inválido impede o wizard com mensagem e comando sugerido, sem crash.
- [ ] Duplicados frágeis exigem confirmação antes do wizard.
- [ ] O monitor exibe sticks em `[-1,1]`, triggers em `[0,1]` e botões com rótulo semântico ou código, com camada (normalizado/calibrado) visível.
- [ ] A leitura do dispositivo ocorre fora da thread da UI; a interface permanece responsiva durante captura de 10 s.
- [ ] Fechar a janela durante monitor ou wizard encerra workers e libera o dispositivo; nenhum `QThread` ativo permanece.
- [ ] O wizard usa `WizardPhase`/`step` e os planos compartilhados em `application/`, sem texto duplicado e sem importar símbolo privado de `calibration_cli`.
- [ ] Retry respeita `STRICT_BLOCKING`; nenhum `Finding` novo é criado pela GUI.
- [ ] Cancelar no wizard preserva artefatos parciais e mostra resumo.
- [ ] Salvamento grava perfil v1 válido e exibe `profile_id`.
- [ ] Perfil inválido aparece com motivo na lista, sem derrubar a tela.
- [ ] Cada situação da matriz de erros tem mensagem e ação correspondentes.
- [ ] Nenhuma mensagem de erro contém stack trace, `sudo` ou caminho absoluto de usuário.
- [ ] Testes Qt rodam em `offscreen` e a suíte completa passa sem display e sem hardware.
- [ ] Nenhum teste novo depende de `/dev/input`, `/sys` real, rede ou `sleep` real.
- [ ] `docs/specs/gui-v1.md`, ADR 0008 e README atualizados, com o placeholder removido.
- [ ] `python scripts/sync_ai_assets.py --check` limpo se `ai/` foi alterado.

## Testes obrigatórios

Use `pytest`, `tmp_path`, fakes e `QT_QPA_PLATFORM=offscreen`. Nenhum hardware.

| Caso | Entrada | Esperado |
| --- | --- | --- |
| Import sem Qt | ambiente sem `PySide6` | `zonepad` e CLI importam; `gui` só importa Qt em `run()` |
| Entry point sem Qt | `zonepad-gui` sem extra | exit `2`, mensagem com comando de instalação |
| Smoke | `zonepad-gui --smoke` offscreen | janela criada, `processEvents`, exit `0` |
| Navegação | troca entre os quatro painéis | estado preservado; foco coerente |
| Lista de dispositivos | snapshot fake com 2 gamepads e 1 unknown | só gamepads listados com ID e status |
| Refresh e watch | snapshots roteirizados | adição/remoção refletidas; sem `sleep` real |
| Mapping ausente | gamepad sem mapping | item marcado; wizard bloqueado com comando sugerido |
| Mapping inválido | `StoredMappingRef.status == "invalid"` | erro com `detail` exibido |
| Identidade frágil | dois IDs com mesma base | confirmação obrigatória antes do wizard |
| Sem permissão | erro de acesso simulado | mensagem sobre grupo `input`, sem `sudo` |
| Monitor normalizado | frame conhecido | stick/trigger nas coordenadas esperadas; rótulo da camada correto |
| Monitor calibrado | perfil + frame | valores calibrados exibidos; centro e deadzone coerentes |
| Coalescência | rajada de 1 000 frames | UI recebe ≤ taxa configurada; último frame prevalece |
| Thread | leitura bloqueante simulada | UI responde a evento durante a leitura |
| Shutdown | fechar janela com worker ativo | worker encerra em < 2 s; dispositivo fechado |
| Wizard fases | eventos roteirizados | estado e efeitos iguais aos de `step` |
| Wizard retry | `SegmentRejected(retry_available=True)` | tela de retry; retry sem inventar severidade |
| Wizard bloqueio | achado bloqueante sem retry | fase `FAILED` com motivo e saída |
| Wizard salvamento | decisão de salvar | `ProfileStore.save` chamado com perfil v1 válido |
| Wizard cancelamento | cancelar na gravação | `abort_capture`, artefatos parciais, resumo |
| Perfis | store com um perfil válido e um inválido | lista mostra ambos; inválido com motivo |
| Arquitetura | AST de `gui/viewmodels/**` | nenhum import de `PySide6`/`os`/`evdev` |
| Regressão | suíte atual | 690 testes continuam verdes |

Adicione um teste que garanta que `run()` só importa Qt após a validação de argumentos, e outro que garanta que nenhum módulo de `gui/` fora de `app.py` cria `QApplication`.

## Validação

Execute e reporte a saída:

```bash
python --version
python -m pytest -q
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_gui_smoke.py
ruff check .
ruff format --check .
mypy src/zonepad
python scripts/sync_ai_assets.py --check
zonepad --help
zonepad-gui --help
QT_QPA_PLATFORM=offscreen zonepad-gui --smoke
```

Smoke manual opcional, com dispositivo real e autorização explícita:

```bash
zonepad devices
zonepad-gui            # selecionar device, abrir monitor, rodar wizard
zonepad calibrate --device <id>   # conferir paridade de instruções e achados
```

Se `ruff format --check` já falhar em `main` em arquivo fora do escopo, registre o débito e não o amplie. Se uma ferramenta não estiver disponível, declare exatamente o que não foi executado. Não execute `sudo`, não altere permissões e não acesse hardware sem confirmação.

## Riscos

| Risco | Impacto | Mitigação |
| --- | --- | --- |
| PySide6 sem wheel para Python 3.15 | GUI não instala | gate da pré-condição 5; parar e pedir decisão; nunca instalar Qt do sistema como contorno |
| Qt headless instável na CI | testes flaky | `offscreen` fixado em `conftest.py`; nenhum display real; smoke isolado; `wait(timeout)` em toda parada de thread |
| Wayland vs X11 | comportamento de janela e foco diferente | testar offscreen; smoke manual nos dois quando possível; declarar o que não foi validado |
| Thread de leitura vazando | app não fecha, dispositivo preso | worker único, `wait(timeout)`, teste de shutdown, log de thread não encerrada |
| Leitura bloqueante na UI | interface travada | `DeviceSession.read` só no worker; teste de responsividade |
| Coalescência errada | perda de amostras relevantes ou CPU alta | taxa configurável em um só lugar, último frame prevalece, teste de rajada |
| Duplicação de lógica do CLI | divergência de instruções/retry | mover planos/textos para `application/`, reutilizar `step`, teste de paridade com `tests/test_calibrate_flow.py` |
| Dependência opcional quebra import | CLI para de funcionar sem `[gui]` | import lazy, teste de import sem Qt, `--smoke` |
| Acessibilidade parcial | usuários de teclado/leitor de tela bloqueados | checklist na etapa 14, `accessibleName`, ordem de tabulação |
| Sem hardware no desenvolvimento | widgets plausíveis mas errados | fakes com capturas sintéticas, revisão de `controller-hardware`, smoke manual declarado |
| Escopo crescer para aplicar perfil | incremento não fecha | D7/D12 excluem aplicar perfil e editar perfis; mudança exige aprovação |
| Perfil inválido derrubar a lista | perda de acesso aos demais | erro por item, teste dedicado |

## Formato de saída

Responda em PT-BR com:

1. **Plano executado** — 3–6 bullets com a ordem real e onde houve handoff.
2. **Spec e decisões** — caminho de `gui-v1.md`, ADR 0008 e D1–D12 fechadas, com o que mudou em relação às recomendações.
3. **Mudanças por arquivo** — `gui/`, view-models, adapters, workers, widgets, painéis, testes e docs.
4. **Contratos** — assinatura de `run`, flags (`--smoke`, `--version`), sinais principais, tipos de estado dos view-models.
5. **Paridade com CLI** — evidência de que instruções, fases e achados do wizard são os mesmos (`tests/test_calibrate_flow.py` e comparação de textos).
6. **Testes e validações** — comandos, resultados e o que não foi executado.
7. **Smoke com hardware** — dispositivo, VID/PID, o que foi visto no monitor e no wizard; declare explicitamente se não foi feito.
8. **Riscos e limitações** — Qt/headless, Wayland/X11, threading, performance, acessibilidade, dependência opcional.
9. **Próximo passo** — handoff para o prompt 06 e o que fica como seam de release.

## Invocação

### Claude Code (prioritária)

```text
Use o prompt em @ai/prompts/05-gui-pyside6.md.
Leia o arquivo inteiro antes de agir e siga a tabela "Etapas e responsáveis" na ordem.
Trabalhe no checkout principal, sem git worktree, na branch feat/gui-pyside6
criada a partir da main; confirme os gates de "Pré-condições" antes de qualquer edição.
Comece com /flow-design-feature e NÃO escreva código de produção antes de a spec
docs/specs/gui-v1.md e o ADR 0008 serem aprovados pelo usuário.
Delegue a controller-hardware: semântica de visualização (unidades, escalas, sticks,
triggers, botões), instruções do wizard, coerência de qualidade/retry e plausibilidade
dos números. Ele não implementa código.
Delegue a python-engineer: aplicação Qt, navegação, view-models sem Qt, threading e
ciclo de vida, adapters de descoberta/mapping/perfis, widgets, wizard GUI, matriz de
erros, testes headless e documentação técnica.
Use prompt-engineer apenas se houver mudança em ai/ ou inconsistência entre prompt,
README, spec e ADR.
Implemente com /flow-implement-feature e faça a revisão final com /flow-review-calibration.
Valide com os comandos da seção "Validação" e entregue o relatório no "Formato de saída".
```

### Codex (alternativa)

```text
Siga o prompt em ai/prompts/05-gui-pyside6.md.
Leia o arquivo inteiro e execute as etapas na ordem, no checkout principal, sem worktree,
na branch feat/gui-pyside6 criada a partir da main.
Use $flow-design-feature para a spec e o ADR, $flow-implement-feature para o código e
$flow-review-calibration para a revisão. Não escreva código antes da aprovação da spec.
Delegue unidades, escalas, semântica de sticks/triggers/botões, instruções do wizard,
qualidade/retry e revisão dos números a controller-hardware.
Delegue GUI, view-models, threading, adapters, widgets, wizard, erros, testes e docs
a python-engineer. Use prompt-engineer apenas para ai/.
Valide com pytest, ruff, mypy, sync --check, zonepad-gui --smoke e o --help do entry point.
```

Se os fluxos não existirem no harness, siga `ai/flows/flow-design-feature/FLOW.md`, `ai/flows/flow-implement-feature/FLOW.md` e `ai/flows/flow-review-calibration/FLOW.md`, e registre o fallback.

## Sequência

- **Prompts 00–04 (concluídos):** toolchain, runtime, métricas, wizard CLI e descoberta/mapping.
- **Prompt 05 (este):** GUI PySide6 como adaptador sobre o núcleo existente.
- **Prompt 06:** qualidade, cobertura, packaging e release.

Não antecipe release, aplicar perfil ao runtime, temas ou suporte a outros sistemas. Se a implementação precisar de uma decisão do prompt 06, registre a pendência e mantenha a GUI isolada atrás de adapters.

## Handoff para o prompt 06

Entregue ao próximo incremento:

1. Versão de PySide6 usada, comandos de instalação e o estado do extra `gui` na CI.
2. Estrutura final de `interface/gui/` e a fronteira view-model ↔ adapter ↔ view.
3. Pontos de entrada e flags (`zonepad-gui`, `--smoke`, `--version`) e exit codes.
4. Lista do que ficou fora do MVP (aplicar perfil, editar perfil, Windows/macOS, temas).
5. Resultado dos smokes (offscreen e manual) e riscos residuais de Qt, threading e acessibilidade.
