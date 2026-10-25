---
name: github-interaction
description: "Executa operações no GitHub via gh e git: inspecionar repositório, criar branches, commits, issues, pull requests, revisões, releases e acompanhar Actions, com segurança e evidência. Use ao publicar, revisar ou sincronizar trabalho com o GitHub."
metadata:
  owner: shared
  version: "1.0"
---

# GitHub Interaction

## Quando usar

Use esta skill para:

- inspecionar o repositório, branches, issues e pull requests;
- criar branch, commit e push de uma mudança;
- abrir, revisar, aprovar ou mesclar um pull request;
- criar ou comentar issues;
- acompanhar GitHub Actions e diagnosticar checks;
- preparar uma release ou tag.

Não use para contornar proteções de branch, reescrever histórico compartilhado ou publicar segredos.

## Pré-requisitos

Verifique antes de qualquer operação:

```bash
gh auth status
gh repo view --json nameWithOwner,defaultBranchRef,viewerPermission
git status --short --branch
git remote -v
```

### Instalação do `gh` (se ausente)

- Arch Linux: `sudo pacman -S github-cli`
- Debian/Ubuntu: `sudo apt install gh`
- macOS: `brew install gh`
- Windows: `winget install --id GitHub.cli`

Não execute `sudo` sem confirmação explícita do usuário. Depois da instalação, autentique com `gh auth login` em um terminal interativo.

Regras:

- `gh` deve estar autenticado; não peça nem armazene tokens em arquivos.
- Para alterar arquivos em `.github/workflows/`, o token precisa do escopo `workflow`. Se `gh auth status` não listar esse escopo, rode `gh auth refresh -s workflow` em terminal interativo.
- Se `gh` não estiver disponível, use `git` para o que for local e peça ao usuário para instalar/autenticar o `gh`.
- Nunca execute `gh auth login` em background; é interativo.
- Nunca imprima `GH_TOKEN`, `GITHUB_TOKEN` ou o conteúdo de `~/.config/gh/hosts.yml`.

## Segurança

- **Leitura primeiro:** diagnostique antes de escrever.
- **Intenção explícita:** push, PR, comentário, merge, release, fechamento e exclusão exigem pedido claro do usuário.
- **Nunca force push** em `main`, `master`, `release/*` ou branch compartilhada.
- **Nunca use `--admin`** para ignorar branch protection ou checks obrigatórios.
- **Não faça merge** com checks falhando, conflitos ou revisão pendente, salvo pedido explícito e justificativa.
- **Confirme ações destrutivas:** apagar branch remota, fechar PR, deletar release, `gh repo delete`.
- **Não commite segredos:** `.env`, tokens, chaves, capturas com serial ou path pessoal.
- **Não reescreva histórico** de branch compartilhada sem confirmação.
- **Use `--draft`** para PR em andamento.

## Fluxo de trabalho

### 1. Diagnosticar

```bash
git status --short --branch
git fetch origin
gh repo view --json nameWithOwner,defaultBranchRef
```

Confirme: repositório correto, branch atual, diff pendente e se há mudanças não commitadas de outra pessoa.

### 2. Sincronizar

```bash
git switch main
git pull --ff-only
```

Se a branch de trabalho existir, faça rebase/merge apenas se o usuário permitir e a branch não for compartilhada.

### 3. Criar branch

```bash
git switch -c feat/<slug>
# ou
git switch -c fix/<slug>
```

Use um slug curto e descritivo. Uma branch por assunto.

### 4. Commitar

```bash
git add -p
git diff --cached
git commit -m "feat(scope): resumo no imperativo"
```

Convenção sugerida:

```text
feat(scope): adiciona ...
fix(scope): corrige ...
docs(scope): atualiza ...
refactor(scope): simplifica ...
test(scope): cobre ...
chore(scope): ajusta ...
```

Regras:

- Um commit deve ser coerente e reversível.
- Não misture refatoração ampla com mudança de comportamento.
- Verifique o diff staged antes de commitar.
- Não use `git add .` sem revisar o que entrou.

### 5. Push

```bash
git push -u origin HEAD
```

Se o push for rejeitado, faça `git fetch` e resolva; não use `--force` sem confirmação.

### 6. Pull request

```bash
gh pr create --draft --title "feat(scope): resumo" --body-file pr.md
```

Corpo mínimo:

```markdown
## Resumo
## Mudanças
## Validação
## Riscos
## Checklist
- [ ] Testes
- [ ] Lint/tipos
- [ ] Documentação
- [ ] `sync_ai_assets.py --check`
```

Use `--draft` até estar pronto. Para PR pronto, remova o draft com `gh pr ready <n>`.

### 7. Checks

```bash
gh pr checks <n> --watch
gh run list --limit 10
gh run view <run-id> --log-failed
```

Não diga que a CI passou sem verificar o estado dos checks. Diagnostique a falha antes de reexecutar.

### 8. Revisão

```bash
gh pr view <n> --json number,title,state,isDraft,mergeable,reviewDecision,statusCheckRollup,url
gh pr diff <n>
gh pr review <n> --comment --body-file review.md
gh pr review <n> --request-changes --body-file review.md
gh pr review <n> --approve
```

Formato de achados:

```markdown
### Blocker
- [arquivo:linha] Problema. Impacto. Correção sugerida.
### High
### Medium
### Low
```

Não aprove com blocker. Não aprove sem entender o diff.

### 9. Merge

```bash
gh pr merge <n> --squash --delete-branch
```

Antes de mergear, confirme:

- checks verdes;
- revisão aprovada;
- branch atualizada;
- sem conflitos;
- autorização do usuário para o merge.

Depois:

```bash
git switch main
git pull --ff-only
git branch -d <branch>
```

## Issues

```bash
gh issue list --state open --limit 20
gh issue view <n> --comments
gh issue create --title "..." --body-file issue.md --label "bug"
gh issue comment <n> --body "..."
gh issue close <n> --comment "..."
```

Corpo de issue:

```markdown
## Contexto
## Comportamento esperado
## Comportamento observado
## Reprodução
## Ambiente
## Evidência
```

Feche uma issue apenas quando houver correção verificada ou decisão explícita.

## Releases

```bash
gh release create vX.Y.Z --generate-notes --title "vX.Y.Z"
gh release view vX.Y.Z
```

Regras:

- Use SemVer quando o projeto seguir SemVer.
- Gere notas e revise antes de publicar.
- Prefira draft release quando o conteúdo ainda não estiver fechado.
- Excluir release é destrutivo; confirme.

## Erros comuns

| Sintoma | Ação |
| --- | --- |
| `gh: not logged in` | Peça autenticação interativa com `gh auth login`. |
| `refusing to allow an OAuth App to create or update workflow` | Falta o escopo `workflow`; rode `gh auth refresh -s workflow`. |
| `Permission denied` | Verifique conta, SSO e permissão no repositório. |
| `protected branch` | Abra PR; não tente bypass. |
| `merge conflict` | Resolva localmente e atualize a branch. |
| Checks falhando | Leia o log com `gh run view --log-failed`; não reexecute às cegas. |
| `no commits between` | Confirme branch, push e base do PR. |
| Push rejeitado | `git fetch` e resolva; não force sem confirmação. |

## Contrato de saída

Ao concluir uma operação, informe:

1. **Ação** — o que foi feito.
2. **Evidência** — URL do PR/issue, SHA, checks ou saída de comando.
3. **Estado** — aberto, draft, merged, falhando, bloqueado.
4. **Riscos** — conflitos, checks pendentes, permissões.
5. **Próximo passo** — se houver.

## Checklist

- [ ] Autenticação e repositório confirmados.
- [ ] Branch correta e diff revisado.
- [ ] Nenhum segredo no commit.
- [ ] Commits coerentes e mensagem clara.
- [ ] PR com resumo, validação e riscos.
- [ ] Checks verificados, não presumidos.
- [ ] Revisão sem blocker antes do merge.
- [ ] Ação destrutiva confirmada.
- [ ] URL/SHA registrados como evidência.
