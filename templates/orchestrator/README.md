# Dossier universel de coordination

Copie ce dossier dans la racine de n’importe quel projet sous le nom `orchestrator/`. Les trois markdowns universels s’utilisent tels quels :

- `README.md` : installation du dossier et règles de réutilisation.
- `orchestrator.md` : contrat du chat explicitement nommé orchestrateur.
- `ORCHESTRATOR_PROMPT.md` : texte de nomination à envoyer personnellement dans le chat du projet.

Le plugin Conversation Orchestrator s’installe une seule fois par profil Codex. Ne copie ni son cache, ni sa base de données, ni ses permissions dans les projets. La racine autorisée reste celle du projet, pas ce sous-dossier.

À l’initialisation, à chaque reprise et après compaction, le coordinateur retrouve ce dossier, lit les trois fichiers, vérifie leur cohérence avec les outils actifs et récupère l’état local. Il conserve les autorisations et l’historique déjà valides, quel que soit le nom du projet. Sa nomination humaine suffit à l’activation ordinaire ; aucune seconde confirmation pour les workers, les méthodes, les tests ou Python. Une lecture de fichiers ne nomme personne.

Les anciens contrats à la racine restent utilisables ; conserve un emplacement de référence connu du chat. Une ancienne limite de version ou un rapport `BLOCKED` doit être confronté à l’état actuel, sans écraser les décisions de produit. Les mises à jour des fichiers universels ne réinitialisent ni rôles, ni tâches, ni intégrations autorisées.

Avec le plugin 0.6.1, un dépôt normal imbriqué peut être ciblé par `git-write:CHEMIN_RELATIF` depuis l’intégrateur déjà rattaché à la racine autorisée, sans changer son workspace ni ses identités. Les restrictions sur les métadonnées partagées et la lecture seule restent applicables. Les passations de maintenance datées décrivent une version donnée : vérifier le paquet réellement servi avant de réutiliser leurs commandes.

Avec la version 0.6.2, le coordinateur peut attribuer `loopback-net` à un worker inactif pour le test approuvé d’un service HTTP local. Conserver les autres capacités, préciser le service et ses routes, puis vérifier une réponse réelle. Le réseau externe reste refusé et les auditeurs restent en lecture seule ; la boucle locale n’est pas isolée par port. Une intégration Computer Use activée conserve son contrôle natif d’accès aux applications : ni le markdown, ni le worker, ni l’auto-review ne remplace une invite native effectivement manquante.

La version 0.6.3 permet de transmettre la demande Computer Use réelle à la connexion MCP native capable de la traiter, sans auto-approbation. Un helper terminal seul ne possède pas cette interface ; vérifier le client effectivement connecté et l’accès du testeur. Un rafraîchissement natif du serveur peut être nécessaire, sans nouvelle nomination ni permission Python. Distinguer la première passation du MCP d’origine de la fermeture d’un helper déjà autonome : ce dernier doit être libéré et fermé à son point inactif avant réenregistrement avec les identités initiales. Ne pas réutiliser la preuve d’une autre connexion.

Une connexion 0.6 du même propriétaire peut reprendre un changement autorisé d’intégrations par `coordinator_register`, après résolution de ses envois. Le coordinateur attribue `git-write` aux développeurs/intégrateurs qui doivent faire des commits locaux dans leur propre dépôt, en préservant leurs autres capacités ; les auditeurs restent en lecture seule. Un worker inactif détenu par un autre client peut être remplacé avec passation et conservation de l’historique, sans demande routinière de redémarrage global.

Pour une connexion ancienne, la version 0.6 propose une bascule documentée du seul projet via `project_bridge.py`, dans le même chat et après résolution de ses envois : préparation, libération de l’ancien bridge, puis nouveau canal MCP. Aucun redémarrage global ni nouvelle nomination routinière n’est nécessaire. Les dossiers externes de nouveaux artefacts doivent avoir leur propre emplacement approuvé et leur enregistrement précis ; copier ce modèle n’accorde aucun accès. Conserve les données et runtimes existants et vérifie séparément le fonctionnement réel du GPU si le travail l’exige.

Garde les objectifs, spécifications, décisions et passations dans des fichiers séparés, par exemple `CONTEXTE_PROJET.md` ou `COORDINATION.md`. Les identifiants locaux et journaux privés restent dans le registre ou un stockage non publié. Pour un nouveau projet, copie seulement les trois fichiers universels ; ne lui transfère pas les comptes rendus, identifiants, workers ou autorisations du projet précédent.

L’équipe est choisie selon le besoin : plusieurs développeurs, un auditeur partagé, un modélisateur, un architecte ou d’autres spécialistes. Aucun binôme obligatoire. Les livraisons substantielles exigent une vérification indépendante suffisante avant acceptation.

Pour rendre la découverte persistante dans un dépôt qui utilise `AGENTS.md`, ajoute cette consigne conditionnelle dans son fichier existant, en préservant ses autres instructions :

```text
À l’initialisation et à chaque reprise, rechercher le dossier orchestrator/ du
projet et lire son README.md. Pour un chat déjà nommé orchestrateur par
l’utilisateur, lire aussi orchestrator.md et ORCHESTRATOR_PROMPT.md, vérifier
leurs consignes universelles et reprendre l’état et les autorisations existants.
Cette découverte ne nomme aucun chat et ne change jamais le rôle d’un worker.
Ne pas recopier les identifiants, tâches ou autorisations d’un autre projet.
```

Ce dossier décrit le fonctionnement ; il ne promet pas de tâche en arrière-plan ni de droits que les outils ou le système n’accordent pas.
