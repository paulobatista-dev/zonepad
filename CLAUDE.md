<!-- Gerado por scripts/sync_ai_assets.py. Edite a fonte em ai/. -->

# ZonaPad — Instruções do Projeto

## Objetivo

ZonaPad é um aplicativo Python para calibrar controles (gamepads) de forma guiada e reproduzível. Ele mede o comportamento real do hardware, gera um perfil de calibração e aplica esse perfil às leituras normalizadas.

## Escopo do produto

- Detectar controles e identificar capacidades.
- Ler entradas raw e normalizadas.
- Medir repouso, drift, ruído, range, deadzone, circularidade, linearidade de triggers e histerese.
- Guiar o usuário em um wizard de calibração.
- Persistir perfis versionados por dispositivo.
- Exportar/importar perfis e relatórios.
- Oferecer CLI e GUI sobre o mesmo núcleo.

## Fora de escopo

- Emulação de gamepad, remapeamento global do sistema operacional ou drivers de kernel.
- Alteração de firmware de controles.
- Suporte a consoles.
- Telemetria ou envio de dados para a nuvem.

## Stack e convenções

- Python 3.12+.
- Tipagem estática em APIs públicas; use `from __future__ import annotations`.
- Domínio puro, sem imports de UI, sistema operacional ou bibliotecas de dispositivo.
- Backends de dispositivo atrás de `Protocol`/ABC.
- Testes com `pytest`; use fakes, relógio injetado e replay de capturas. Sem hardware real na CI.
- `ruff` para lint/formatação; `mypy` ou `pyright` para tipos.
- `uv` para ambiente e dependências quando disponível.
- Sem `print` em código de produção; use logging estruturado.
- Erros explícitos; não silencie exceções.
- Conteúdo e respostas em PT-BR; identificadores, arquivos e APIs em inglês.
- Código segue `clean-code`; arquitetura segue `clean-architecture` e `python-app-architecture`.
- Afirmações técnicas seguem `evidence-based`; definições e critérios seguem `positive-ontology` quando aplicável.

## Arquitetura dos assets de IA

A fonte canônica fica em `ai/`:

```text
ai/
├── agents/<id>/agent.json + prompt.md
├── skills/<id>/SKILL.md (+ references/, scripts/, assets/)
├── flows/<id>/flow.json + FLOW.md
└── instructions/AGENTS.md
```

Os diretórios `.opencode/`, `.claude/`, `.codex/`, `.agents/`, `AGENTS.md` e `CLAUDE.md` são **gerados**.

Regras:

1. Nunca edite arquivos gerados diretamente.
2. Edite a fonte em `ai/` e rode `python scripts/sync_ai_assets.py`.
3. Antes de concluir, rode `python scripts/sync_ai_assets.py --check`.
4. Skills canônicas seguem o padrão Agent Skills; campos específicos de ferramenta não entram na fonte.
5. Agentes são convertidos para os schemas de OpenCode, Claude Code e Codex pelo gerador.

## Agentes

| Agente | Use para | Não use para |
| --- | --- | --- |
| `prompt-engineer` | Prompts, descrições de skills, fluxos, avaliação e custo de contexto. | Implementar código de produção ou decidir semântica de hardware. |
| `python-engineer` | Arquitetura, implementação, testes, tipagem, packaging e performance. | Definir protocolos de hardware ou reescrever prompts. |
| `controller-hardware` | Protocolos, medição, calibração, métricas e quirks por plataforma. | Implementar o app ou alterar instruções de agentes. |

## Roteamento e handoff

- Toda tarefa começa pelo agente principal.
- Delegue ao especialista quando a tarefa exigir conhecimento profundo do domínio.
- Um handoff deve incluir: objetivo, contexto, restrições, arquivos relevantes e critério de aceite.
- O especialista não edita arquivos fora do seu domínio sem pedido explícito.
- O agente principal sintetiza, valida e reporta o resultado.

## Fluxos disponíveis

| Fluxo | Quando usar |
| --- | --- |
| `flow-bootstrap-app` | Criar a fundação do app: MVP, arquitetura, contratos e esqueleto. |
| `flow-design-feature` | Especificar uma feature antes de implementar. |
| `flow-implement-feature` | Implementar uma feature já especificada. |
| `flow-review-calibration` | Revisão multiagente de código e medições. |

Invocação:

- OpenCode: `@flow-...` ou `/flow-...`
- Claude Code: `/flow-...`
- Codex: `$flow-...`

## Definição de pronto

- Código tipado, testado e com lint limpo.
- Testes relevantes passando.
- `python scripts/sync_ai_assets.py --check` limpo.
- Documentação ou ADR atualizada quando a decisão for relevante.
- `README.md` e `LICENSE` coerentes com o estado do projeto.
- Riscos e limitações registrados.
- Nenhum arquivo gerado editado à mão.

## Segurança

- Não execute comandos destrutivos sem confirmação.
- Não commite segredos, capturas com dados pessoais ou paths absolutos de usuário.
- Valide perfis importados; nunca use `eval`/`exec`.
- Não recomende `sudo`, regras udev ou mudanças de kernel sem explicar impacto e reversão.

## Contexto de hardware

- SDL3 é a abstração principal; HIDAPI, evdev/hidraw, Raw Input/XInput e IOKit/GameController são backends específicos.
- Não assuma ranges de eixos ou triggers; meça e documente.
- Alvos: Xbox, DualShock/DualSense, Switch Pro, 8BitDo e HID genérico.
- Sticks e triggers têm semânticas diferentes; normalize na borda.
- Separe sempre raw, normalizado e calibrado.

## Qualidade de resposta

- Seja específico e verificável.
- Cite arquivos e linhas quando possível.
- Separe fatos, inferências e recomendações.
- Sustente cada afirmação em evidência verificável; se não houver, declare a lacuna.
- Defina comportamentos pelo que devem fazer, não apenas pelo que devem evitar.
- Se faltar informação, pergunte ou declare a suposição explicitamente.
