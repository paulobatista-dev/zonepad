---
name: positive-ontology
description: "Define comportamentos, termos e critérios de forma afirmativa e observável, evitando ontologia negativa. Use ao escrever prompts, skills, specs, contratos, ADRs, mensagens de erro ou respostas; preserve negações apenas para limites reais de segurança e escopo."
metadata:
  owner: prompt-engineer
  version: "1.0"
---

# Positive Ontology

## Quando usar

Use esta skill quando estiver definindo:

- o comportamento de um agente ou o contrato de uma skill;
- um termo de domínio, uma métrica ou um critério de aceite;
- uma regra de arquitetura, uma mensagem de erro ou um ADR;
- uma recomendação que precisa ser executável sem ambiguidade.

Não use para eliminar toda negação. Proibições de segurança, escopo e compatibilidade continuam necessárias; o problema é a **definição incompleta por negação**.

## O que é ontologia negativa

Ontologia negativa é definir algo principalmente pelo que ele **não é**, ou instruir apenas com proibições, sem dizer qual é o comportamento desejado.

Exemplos:

- "Não seja vago."
- "Não invente."
- "Não bloqueie a UI."
- "Não use código ruim."

O leitor sabe o que evitar, mas precisa adivinhar o alvo. Em agentes, isso produz respostas que satisfazem a letra da proibição e falham no resultado.

## Regra central

Toda negação relevante deve vir acompanhada de:

1. **Comportamento desejado** — o que fazer em vez disso.
2. **Critério observável** — como saber que o comportamento aconteceu.
3. **Fronteira** — quando a proibição se aplica e quando não se aplica.

Se a negação não puder ser convertida em comportamento positivo, ela provavelmente é vaga ou pertence a outra camada.

## Quando a negação é legítima

Use negação explícita para:

- **Segurança:** impedir ações destrutivas, vazamento de dados ou execução arbitrária.
- **Escopo:** impedir que o agente invada o domínio de outro especialista.
- **Compatibilidade:** impedir o uso de uma API que quebra uma plataforma.
- **Conformidade:** impedir uma prática proibida por política ou lei.

Nesses casos, ainda entregue a alternativa:

```text
Não execute comandos destrutivos sem confirmação.
Faça: apresente o comando, o alvo e o efeito; peça confirmação explícita.
```

## Reescritas

| Ontologia negativa | Formulação positiva |
| --- | --- |
| "Não seja vago." | "Cite arquivo e linha; se não houver evidência, declare a lacuna." |
| "Não invente APIs." | "Confirme a API na documentação da versão; se não encontrar, escreva 'não verificado'." |
| "Não bloqueie a UI." | "Leia o dispositivo em um worker e publique snapshots imutáveis; a UI consome o último snapshot." |
| "Não use god classes." | "Cada classe tem uma responsabilidade; se um método mistura persistência e UI, separe." |
| "Não faça code review ruim." | "Liste achados por severidade, com arquivo:linha, impacto e correção." |
| "Não assuma o range." | "Meça o range com uma captura e registre mínimo, máximo e repouso." |

## Definições afirmativas

Uma definição útil contém:

1. **Termo** — o nome exato.
2. **Propriedades necessárias** — o que sempre está presente.
3. **Propriedades suficientes** — o que distingue o termo de vizinhos.
4. **Unidade/domínio** — counts, [-1, 1], [0, 1], segundos.
5. **Exemplo** — um caso concreto.
6. **Fronteira** — o que fica fora, com o critério positivo.

Exemplo:

```text
Deadzone radial: região circular em torno do centro do stick onde a saída é zero.
Unidade: normalizada, raio em [0, 1].
Exemplo: centro (0, 0), raio 0.08; qualquer ponto com ||p|| <= 0.08 vira (0, 0).
Fronteira: deadzone axial usa |x| e |y| separadamente; não é o padrão do ZonaPad.
```

Evite:

- definição circular ("calibração é o processo de calibrar");
- dupla negação ("não é incomum" em vez de "é comum");
- definição apenas por contraste ("é o oposto de X");
- termo sem unidade ou sem critério de observação.

## Aplicação por artefato

### Prompt de agente

Descreva o comportamento desejado, o processo e o contrato de saída. Use proibições apenas para limites reais e sempre com alternativa.

### Skill

A descrição diz **quando usar**; o corpo diz **como fazer**. Não defina a skill apenas pelo que ela não cobre.

### Spec ou ADR

Critérios de aceite devem ser observáveis. "Não pode falhar" não é critério; "mantém drift < 0,02 em 5 s de repouso" é.

### Código

Nomes, docstrings e mensagens de erro devem dizer o que o código faz e o que o usuário deve fazer. Evite mensagens como "operação inválida"; prefira "o perfil não tem `schema_version`; adicione o campo ou migre o arquivo".

### Resposta

Comece pela recomendação positiva. Mencione o que evitar depois, como consequência ou fronteira.

## Anti-padrões

- Proibição sem comportamento alternativo.
- "Nunca" sem escopo, detecção ou exceção.
- Definir um conceito apenas pelo que ele não é.
- Dupla negação.
- Regra de segurança escondida entre preferências de estilo.
- Proibição que o agente não consegue verificar.
- Usar "não" para substituir um critério de aceite.

## Checklist

- [ ] O comportamento principal está afirmado.
- [ ] Cada proibição relevante tem uma alternativa positiva.
- [ ] Cada definição tem propriedades, unidade e fronteira.
- [ ] Os critérios de aceite são observáveis.
- [ ] Não há dupla negação.
- [ ] Proibições de segurança estão explícitas e delimitadas.
- [ ] O leitor consegue agir sem adivinhar o oposto.

<!-- Gerado por scripts/sync_ai_assets.py. Edite ai/skills/positive-ontology/SKILL.md. -->
