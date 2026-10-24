# ADR 0001 — Fonte canônica e espelhamento entre agentes

- **Status:** aceito
- **Data:** 2026-10-24

## Contexto

O projeto precisa dos mesmos agentes, skills e fluxos em três ferramentas:

- OpenCode: agentes em `.opencode/agents/*.md`, skills em `.opencode/skills/`, comandos em `.opencode/commands/`.
- Claude Code: agentes em `.claude/agents/*.md`, skills em `.claude/skills/`.
- Codex: agentes em `.codex/agents/*.toml`, skills em `.agents/skills/`.

Os schemas não são equivalentes. OpenCode usa `permissions`; Claude usa `tools` e `skills`; Codex usa TOML com `developer_instructions`. Além disso, prompts customizados do Codex estão deprecated e são globais, então fluxos precisam ser skills com invocação explícita.

Cópias manuais divergem. Symlinks não convertem schema e são frágeis no Windows.

## Decisão

1. Manter uma fonte canônica em `ai/`, versionada no repositório.
2. Usar `scripts/sync_ai_assets.py` para gerar os três espelhos.
3. Tratar agentes como dados estruturados (`agent.json` + `prompt.md`) e convertê-los por alvo.
4. Manter skills canônicas no padrão Agent Skills e copiá-las para os três destinos.
5. Representar fluxos como skills com `disable-model-invocation: true`; gerar comandos `/flow-...` apenas para OpenCode.
6. Validar o espelhamento com `--check` na CI.
7. Nunca editar arquivos gerados à mão.

## Consequências

- Uma mudança em `ai/` se propaga de forma determinística.
- O repositório contém arquivos gerados, mas todos são reproduzíveis.
- O gerador precisa ser mantido quando um schema mudar.
- O Codex não aplica restrições de ferramenta por agente; as regras de escopo são comportamentais.
- O Claude pré-carrega skills listadas no agente, o que aumenta o contexto do subagente.
- O OpenCode não cria slash commands a partir de skills; comandos de fluxo são gerados separadamente.

## Alternativas consideradas

- **Symlinks:** menos arquivos, mas não resolvem a conversão de schema e falham em ambientes sem suporte.
- **Cópias manuais:** simples no início, com alto risco de drift e revisões inconsistentes.
- **Plugin único:** distribuível, mas adiciona empacotamento e ainda exigiria adaptação por ferramenta.
- **Só `.agents/skills`:** funciona para Codex e OpenCode, mas Claude Code não lê esse diretório.

## Validação

```bash
python scripts/sync_ai_assets.py --check
python -m unittest discover -s tests -v
```

A CI executa os dois comandos em push e pull request.
