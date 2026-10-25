---
name: flow-bootstrap-app
description: "Cria a fundação do ZonaPad: escopo do MVP, arquitetura, contratos de dispositivo, esqueleto Python e plano de testes. Use ao iniciar o projeto ou ao reconstruir a base."
disable-model-invocation: true
argument-hint: "[objetivo] [plataformas] [dispositivos]"
---

<!-- Gerado por scripts/sync_ai_assets.py. Edite a fonte em ai/. -->

# Fluxo: Bootstrap do app

## Quando usar

Use este fluxo quando o ZonaPad ainda não tem uma base executável ou quando a fundação precisa ser reconstruída. Não use para adicionar uma feature a um app já estruturado; prefira `flow-design-feature` e `flow-implement-feature`.

## Entradas

- Objetivo do MVP e público.
- Plataformas prioritárias (Linux, Windows, macOS).
- Controles alvo e conexão (USB/Bluetooth).
- Restrições de UI, empacotamento e prazo.
- O que está fora de escopo.

Se alguma entrada essencial faltar, pergunte antes de começar. Declare suposições.

## Passos

1. **Ler o contexto** — `AGENTS.md`, esta skill, `calibration-domain`, `python-app-architecture`, `controller-protocols` e `calibration-metrics`.
2. **Fixar o MVP** — uma frase de objetivo, 3–5 capacidades, 3–5 não-objetivos e critérios de sucesso observáveis.
3. **Delegar ao hardware** — peça a `controller-hardware`:
   - abstração de dispositivo e capabilities;
   - dispositivos alvo e backends por plataforma;
   - modelo de frames raw/normalizado;
   - métricas e protocolo de captura do MVP;
   - riscos e validações pendentes.
4. **Delegar ao Python** — peça a `python-engineer`:
   - layout de módulos e dependências;
   - portas e contratos;
   - estratégia de concorrência e hot-plug;
   - estratégia de testes com fakes/replay;
   - plano de skeleton e critérios de pronto.
5. **Delegar ao prompt** — peça a `prompt-engineer` apenas se a fundação exigir mudança em agentes, skills, fluxos ou `AGENTS.md`.
6. **Sintetizar** — produza uma proposta única de MVP + arquitetura + backlog. Resolva conflitos explicitamente; não concatene respostas contraditórias.
7. **Aprovar** — apresente a proposta ao usuário e obtenha aprovação antes de criar código.
8. **Implementar o skeleton** — com `python-engineer`:
   - `pyproject.toml` e layout `src/zonepad/`;
   - modelos de domínio e funções puras;
   - portas de dispositivo, relógio e store;
   - backend fake e replay;
   - CLI mínima e testes;
   - `README.md` com visão geral, instalação, uso, arquitetura e licença;
   - `LICENSE` com a licença MIT;
   - nenhuma dependência de hardware real na CI.
9. **Validar** — rode lint, tipos, testes e `python scripts/sync_ai_assets.py --check`, quando aplicável.
10. **Documentar** — ADR da arquitetura, README de execução, licença MIT e próximo backlog.

## Como delegar

Use o mecanismo de subagentes da ferramenta atual:

- OpenCode: ferramenta `subagent`, com o ID do agente.
- Claude Code: ferramenta Agent, com `subagent_type`.
- Codex: subagente, nomeando o agente customizado.

Um handoff deve conter: objetivo, contexto, restrições, arquivos relevantes, formato de saída e critério de aceite.

## Saída esperada

```markdown
## MVP
- Objetivo:
- Capacidades:
- Não-objetivos:
- Critérios de sucesso:

## Arquitetura
- Camadas e módulos:
- Portas e contratos:
- Concorrência:
- Persistência:

## Hardware
- Dispositivos/backends:
- Frames e unidades:
- Métricas do MVP:
- Riscos:

## Plano
- Arquivos a criar:
- Testes:
- Ordem de implementação:

## Documentação
- README:
- Licença: MIT

## Riscos e decisões pendentes
```

## Critérios de pronto

- [ ] MVP e não-objetivos estão explícitos.
- [ ] A arquitetura respeita a regra de dependência.
- [ ] Contratos de dispositivo estão definidos.
- [ ] O skeleton executa e os testes passam sem hardware.
- [ ] Há fake/replay para o caminho de leitura.
- [ ] `README.md` cobre visão geral, instalação, uso e arquitetura.
- [ ] `LICENSE` contém a licença MIT.
- [ ] `pyproject.toml` declara a licença MIT.
- [ ] Riscos e decisões pendentes estão registrados.
- [ ] Nenhum arquivo gerado foi editado à mão.
