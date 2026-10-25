# ADR 0007 — Modos direto e subagente

- **Status:** aceito
- **Data:** 2026-10-25

## Contexto

Os agentes do projeto nasceram como subagentes. O uso como agente principal era possível apenas no OpenCode, e dependia de editar o `mode` gerado. O mesmo especialista precisa poder:

- **direto** — conduzir a sessão, pedir esclarecimentos ao usuário e delegar trabalho delimitado;
- **subagente** — receber uma tarefa do agente pai, executá-la e devolver resultado, evidências e riscos.

As três ferramentas não têm o mesmo modelo:

- **OpenCode** aceita `mode: primary`, `subagent` ou `all`; `all` habilita os dois usos.
- **Claude Code** usa o mesmo `.claude/agents/<id>.md` como subagente (tool Agent) e como agente principal (`--agent <id>` ou setting `agent`); não há campo de modo no frontmatter.
- **Codex** usa `.codex/agents/<id>.toml` apenas para subagentes. O modo direto é um perfil em `$CODEX_HOME/<id>.config.toml`, carregado com `--profile <id>`; o `.codex/config.toml` do projeto ignora `profiles`.

## Decisão

1. Declarar na fonte canônica `modes: ["direct", "subagent"]`, com vocabulário portátil.
2. Mapear os modos por ferramenta:
   - OpenCode: `all`, `primary` ou `subagent`;
   - Claude Code: um único arquivo, com o modo direto documentado;
   - Codex: `.codex/agents/<id>.toml` para subagente e `.codex/profiles/<id>.config.toml` para direto.
3. Incluir a ferramenta `subagent` nos agentes, para que o modo direto possa delegar aos especialistas.
4. Explicar os dois modos no prompt de cada agente.
5. Documentar a instalação reversível do perfil Codex em `$CODEX_HOME`; o repositório não escreve no home do usuário.
6. Manter um único prompt por agente; a diferença de modo é de empacotamento e de comportamento, não de conteúdo duplicado.

## Consequências

- A mesma fonte gera os dois modos para as três ferramentas.
- O modo é aplicado nativamente no OpenCode e no Codex; no Claude Code ele é informativo, porque o mesmo arquivo serve aos dois contextos.
- O modo direto no Codex exige uma instalação por máquina (symlink ou cópia em `$CODEX_HOME`). No Windows, a cópia precisa ser repetida após o sync.
- `developer_instructions` do perfil Codex é aditivo. Um `.codex/config.toml` de projeto que defina a mesma chave tem precedência.
- Adicionar `subagent` amplia a permissão de delegação. Os prompts delimitam quando delegar e o contrato de retorno do subagente.
- Perfis Codex repetem o prompt do agente; a duplicação é gerada e verificada por `--check`.

## Alternativas consideradas

- **Manter `mode` e usar `all`:** mudança menor, mas mantém vocabulário específico do OpenCode na fonte canônica.
- **Só documentar o modo direto no Codex:** simples, mas não entrega um artefato reproduzível.
- **Script wrapper com `codex -c`:** evita `$CODEX_HOME`, mas adiciona código e foge do mecanismo nativo de perfis.
- **Dois prompts por agente:** duplica conteúdo e aumenta o risco de divergência.

## Validação

```bash
python scripts/sync_ai_assets.py
python scripts/sync_ai_assets.py --check
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy src/zonepad
opencode debug agents
```

## Referências

- OpenCode V2, Agents: <https://opencode.ai/v2/docs/agents/>
- Claude Code, subagentes: <https://code.claude.com/docs/en/sub-agents>
- Claude Code, CLI (`--agent`): <https://code.claude.com/docs/en/cli-reference>
- Codex, subagentes e agentes customizados: <https://learn.chatgpt.com/docs/agent-configuration/subagents>
- Codex, configuração e perfis: <https://learn.chatgpt.com/docs/config-file/config-advanced>
