---
name: prompt-design
description: Projeta e revisa prompts de sistema, descrições de skills e instruções de fluxo para agentes de IA, com foco em clareza, testabilidade e portabilidade entre OpenCode, Claude Code e Codex. Use ao criar ou ajustar agentes, skills, fluxos ou contratos de comportamento.
metadata:
  owner: prompt-engineer
  version: "1.0"
---

# Prompt Design

## Quando usar

Use esta skill para:

- criar ou reescrever o prompt de um agente;
- decidir se uma instrução pertence a agente, skill, fluxo ou `AGENTS.md`;
- escrever a descrição que faz uma skill ser descoberta;
- revisar instruções contraditórias, vagas ou caras em tokens;
- preparar uma mudança para ser avaliada com `prompt-evaluation`.

Não use para implementar código, definir protocolos de hardware ou julgar medições.

## Decisão de artefato

| Necessidade | Artefato | Pergunta de controle |
| --- | --- | --- |
| Quem é o especialista e quais são seus limites | Agente (`ai/agents/*/prompt.md`) | Isso muda o comportamento em toda tarefa do agente? |
| Como executar uma tarefa ou consultar conhecimento | Skill (`ai/skills/*/SKILL.md`) | Isso só é necessário quando a tarefa é específica? |
| Sequência com handoffs e critérios de pronto | Fluxo (`ai/flows/*/FLOW.md`) | Isso orquestra mais de um agente ou etapa? |
| Regra que vale para todo o projeto | `ai/instructions/AGENTS.md` | Todos precisam saber isso em toda sessão? |

Se a mesma regra aparecer em dois lugares, escolha um dono e referencie o outro.

## Anatomia de um prompt de agente

1. **Papel** — quem o agente é e qual perspectiva adota.
2. **Missão** — o resultado que ele existe para produzir.
3. **Escopo** — o que faz e o que não faz.
4. **Princípios** — critérios de decisão, não slogans.
5. **Processo** — passos ordenados e verificáveis.
6. **Regras** — obrigatório, recomendado e proibido.
7. **Contrato de saída** — formato e conteúdo da resposta.
8. **Handoffs** — quando passar a outro especialista.
9. **Limites** — o que nunca fazer.

Um bom prompt responde: "Como eu sei que o trabalho terminou?" Se a resposta não for observável, falta critério.

## Template

```markdown
# Papel

Você é <especialidade> do <projeto>. <Perspectiva e missão em 1–2 frases.>

## Missão

<Resultado concreto.>

## Escopo

Atue em:
- <domínio 1>
- <domínio 2>

Não atue em:
- <fora de escopo>

## Processo

1. <Passo verificável.>
2. <Passo verificável.>
3. <Validação.>

## Regras

- <Obrigatório.>
- <Recomendado.>
- <Proibido.>

## Contrato de saída

Responda com:
1. <Seção 1>
2. <Seção 2>

## Handoffs

- <Situação> → `<agente>`.

## Limites

- <O que nunca fazer.>
```

## Descrições de skills

A descrição é o único texto que o modelo vê antes de decidir carregar a skill. Ela precisa conter:

- o caso de uso principal;
- palavras-gatilho que o usuário ou o agente usariam;
- a fronteira ("não use para..."), quando houver risco de confusão.

Padrão:

```text
<Verbo no presente> <objeto>, <resultado>. Use quando <gatilhos>. Não use para <exclusões>.
```

Exemplo:

```text
Valida a semântica de medições de sticks e triggers, incluindo deadzone, ruído e circularidade. Use ao revisar calibração ou interpretar capturas. Não use para implementar a UI.
```

Evite descrições genéricas ("Ajuda com prompts"), nomes internos sem contexto e listas longas de palavras-chave.

## Portabilidade

A fonte canônica fica em `ai/` e é convertida para três ferramentas:

- OpenCode: agentes em Markdown com `permissions`;
- Claude Code: agentes em Markdown com `tools`/`skills`;
- Codex: agentes em TOML com `developer_instructions`.

Regras:

- Não use sintaxe específica de uma ferramenta no corpo do prompt.
- Não conte com um campo de frontmatter que só existe em uma ferramenta.
- Quando uma capacidade não existe em todas, declare o fallback no texto.
- Fluxos são skills com invocação explícita; não dependam de comandos customizados do Codex, que estão deprecated.
- Skills usam apenas campos do padrão Agent Skills (`name`, `description`, `metadata`, `license`, `compatibility`).

## Orçamento de contexto

- Prompt de agente: idealmente até 150 linhas.
- `SKILL.md`: idealmente até 500 linhas e menos de ~5.000 tokens.
- Tabelas grandes, catálogos e exemplos extensos vão para `references/`.
- O corpo da skill deve dizer **quando** ler cada referência, não despejar tudo.
- Remova repetições antes de adicionar novas regras.

## Anti-padrões

- "Seja detalhado", "seja útil", "faça o melhor" sem critério.
- Regras que se contradizem sem ordem de prioridade.
- Exemplos que ensinam um formato que o contrato de saída não pede.
- Instruções que dependem de memória de conversas anteriores.
- Copiar o mesmo conteúdo em agente + skill + fluxo.
- Descrição de skill que não distingue a skill de outra parecida.
- Prompt que tenta compensar uma limitação do harness com uma promessa falsa.
- Segurança tratada como preferência, não como regra.

## Checklist

- [ ] O papel e a missão cabem em duas frases.
- [ ] O escopo tem "faz" e "não faz".
- [ ] O processo termina em validação observável.
- [ ] O contrato de saída é explícito.
- [ ] As regras separam obrigatório de recomendado.
- [ ] A descrição da skill contém gatilhos e fronteira.
- [ ] Não há duplicação entre artefatos.
- [ ] O texto não depende de uma ferramenta específica.
- [ ] O custo de contexto é justificável.
- [ ] A mudança pode ser testada por `prompt-evaluation`.

<!-- Gerado por scripts/sync_ai_assets.py. Edite ai/skills/prompt-design/SKILL.md. -->
