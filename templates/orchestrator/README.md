# Dossier universel de coordination

Copie ce dossier dans la racine de n’importe quel projet sous le nom `orchestrator/`. Les trois markdowns universels s’utilisent tels quels :

- `README.md` : installation du dossier et règles de réutilisation.
- `orchestrator.md` : contrat du chat explicitement nommé orchestrateur.
- `ORCHESTRATOR_PROMPT.md` : texte de nomination à envoyer personnellement dans le chat du projet.

Le plugin Conversation Orchestrator s’installe une seule fois par profil Codex. Ne copie ni son cache, ni sa base de données, ni ses permissions dans les projets. La racine autorisée reste celle du projet, pas ce sous-dossier.

À l’initialisation, à chaque reprise et après compaction, le coordinateur retrouve ce dossier, lit les trois fichiers, vérifie leur cohérence avec les outils actifs et récupère l’état local. Il conserve les autorisations et l’historique déjà valides, quel que soit le nom du projet. Sa nomination humaine suffit à l’activation ordinaire ; aucune seconde confirmation pour les workers, les méthodes, les tests ou Python. Une lecture de fichiers ne nomme personne.

Les anciens contrats à la racine restent utilisables ; conserve un emplacement de référence connu du chat. Une ancienne limite de version ou un rapport `BLOCKED` doit être confronté à l’état actuel, sans écraser les décisions de produit. Les mises à jour des fichiers universels ne réinitialisent ni rôles, ni tâches, ni intégrations autorisées.

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
