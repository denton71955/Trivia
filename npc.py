{
  "npcs": [
    {
      "id": "npc_warrior_01",
      "name": "Arion",
      "type": "warrior",
      "baseStats": {
        "health": 150,
        "attack": 25,
        "defense": 20,
        "speed": 1.2
      },
      "abilities": ["slash", "shield_bash"],
      "modelPath": "assets/models/characters/warrior.glb",
      "spawnChance": 0.25
    },
    {
      "id": "npc_goblin_01",
      "name": "Goblin",
      "type": "enemy",
      "baseStats": {
        "health": 40,
        "attack": 10,
        "defense": 5,
        "speed": 2.5
      },
      "abilities": ["scratch"],
      "modelPath": "assets/models/enemies/goblin.glb",
      "spawnChance": 0.75
    }
  ]
}
