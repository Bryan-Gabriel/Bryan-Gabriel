# Cartões combinados do perfil

O README usa três SVGs gerados pela API oficial do GitHub. Cada cartão soma a atividade pública com a dos repositórios privados listados em um Secret. Nenhum cartão privado separado é exibido. O workflow roda uma vez por dia e também aceita execução manual.

Repositórios públicos entram mesmo quando você é colaborador e não é o proprietário, desde que seus commits, PRs ou issues apareçam na busca do GitHub. Repositórios privados em que você colabora entram somente se estiverem em `PROFILE_STATS_REPOS` **e** o token clássico tiver acesso a eles. O gerador falha se um privado listado não estiver acessível, para não publicar números incompletos silenciosamente.

## O que entra

- **Atividade:** total histórico de commits, PRs e issues criados pela conta, desde a criação da conta, mais as sequências de dias com ao menos uma dessas atividades. A sequência atual considera atividade hoje ou ontem; a maior sequência cobre o histórico consultado.
- **Estatísticas:** commits, PRs e issues do ano corrente em UTC. Commits são buscados na branch padrão de cada repositório. PRs não são contados como issues.
- **Linguagens:** bytes classificados pelo GitHub nos repositórios públicos encontrados no histórico e em todos os privados listados. Não representam autoria individual.

Revisões de PR, discussões, comentários, commits que não chegaram à branch padrão e outras atividades não entram. Os totais podem divergir do gráfico oficial do GitHub. A API de busca limita cada consulta anual a 1.000 resultados e até 4.000 repositórios pesquisados; o gerador interrompe a publicação se houver mais de 1.000 resultados ou busca incompleta, mas não há garantia de cobertura além do limite de 4.000 repositórios.

## Configuração no GitHub

1. Crie um token pessoal **clássico** em **Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token (classic)**. Dê um nome identificável, defina uma expiração curta e marque o escopo `repo`, necessário para ler repositórios privados. Se uma organização usar SSO/SAML, autorize o token para ela. Se a organização bloquear tokens clássicos, ela precisará permitir esse acesso ou será necessário outro tipo de credencial.
2. No repositório público do perfil, abra **Settings → Secrets and variables → Actions → New repository secret**. Crie `PROFILE_STATS_TOKEN` com o token e `PROFILE_STATS_REPOS` com a lista `owner/repo1,owner/repo2`, sem espaços obrigatórios. Use **Secrets**, não Variables. Os nomes não devem ser inseridos no README nem no workflow.
3. Publique o código do README, script e workflow na branch padrão do repositório de perfil. O workflow precisa estar nessa branch para aparecer em **Actions**.
4. Em **Actions → Atualizar estatisticas completas do perfil → Run workflow**, execute uma vez. Verifique o job. Em caso de sucesso, o bot cria os três SVGs em `assets/` e troca somente o bloco marcado no README. Depois disso, a rotina diária mantém os cartões atualizados.

Se o job gerar os SVGs mas o `git push` falhar por falta de permissão, confira **Settings → Actions → General → Workflow permissions** e a política da conta. O workflow solicita somente `contents: write` para publicar o README e os SVGs; não use o token privado para fazer o push.

O token clássico com escopo `repo` pode acessar **todos os repositórios privados que sua conta consegue acessar**, inclusive de várias organizações, e tem permissões mais amplas que a leitura necessária ao gerador. O código inclui nos cartões somente os privados listados em `PROFILE_STATS_REPOS`, mas isso **não limita o poder do token**. Restrinja quem pode alterar o workflow na branch padrão, use expiração curta e revogue o token se suspeitar de exposição. O token não dá acesso a repositórios aos quais sua conta não tenha acesso.

## Teste local opcional

Copie `.env.example` para `.env`, preencha usuário, token e lista e rode `python scripts/private_stats.py`. O arquivo `.env` está ignorado pelo Git. No Actions, o script ignora o `.env` e usa apenas os Secrets. Não envie o arquivo, nem cole o token em logs ou mensagens.

Os SVGs publicam intencionalmente os totais e nomes de linguagens. Isso revela estatísticas agregadas, embora não revele nomes de projetos, código ou token. Revise os SVGs antes da primeira publicação se até os agregados forem confidenciais. Em caso de erro de busca ou autenticação, o script falha sem substituir os cartões anteriores. Renovar o token e atualizar o Secret antes da expiração faz parte da manutenção.
