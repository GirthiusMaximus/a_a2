"""Curated example map recipes (requirement #1)."""

PRESETS = [
    {
        "key": "vanilla_4000",
        "label": "Vanilla-style Island 4000",
        "description": "A classic procedural-style island: ridged highlands, rivers, full biome spread.",
        "recipe": {"name": "Vanilla-style Island", "size": 4000, "seed": 90210,
                   "theme": "classic"},
    },
    {
        "key": "circular_3000",
        "label": "Circular Isle 3000",
        "description": "A clean ring-beached round island with a mountainous core.",
        "recipe": {"name": "Circular Isle", "size": 3000, "seed": 777,
                   "theme": "circular_isle"},
    },
    {
        "key": "volcano_3500",
        "label": "Volcano 3500",
        "description": "One huge volcano, caldera crater, rocky ash slopes.",
        "recipe": {"name": "Volcano", "size": 3500, "seed": 6660,
                   "theme": "volcano", "mountain_scale": 1.4},
    },
    {
        "key": "archipelago_4000",
        "label": "Archipelago 4000",
        "description": "Island chains and shallow seas — bring a boat.",
        "recipe": {"name": "Archipelago", "size": 4000, "seed": 20425,
                   "theme": "archipelago"},
    },
    {
        "key": "naval_4500",
        "label": "Naval 4500",
        "description": "Mostly ocean, small island outposts, maximum water warfare.",
        "recipe": {"name": "Naval", "size": 4500, "seed": 1700,
                   "theme": "naval", "land_ratio": 0.3},
    },
    {
        "key": "moon_3000",
        "label": "Moon 3000",
        "description": "Grey cratered regolith, no vegetation, no open water.",
        "recipe": {"name": "Moon", "size": 3000, "seed": 1969,
                   "theme": "moon", "biome_blacklist": ["jungle"]},
    },
    {
        "key": "mars_3500",
        "label": "Mars 3500",
        "description": "Rust-red dunes, impact craters, dry ridgelines.",
        "recipe": {"name": "Mars", "size": 3500, "seed": 2030,
                   "theme": "mars"},
    },
    {
        "key": "canyon_3500",
        "label": "Canyonlands 3500",
        "description": "Terraced mesas and deep carved canyons.",
        "recipe": {"name": "Canyonlands", "size": 3500, "seed": 435,
                   "theme": "canyonlands", "mountain_scale": 1.25},
    },
    {
        "key": "builder_2000",
        "label": "Builder Flatlands 2000",
        "description": "Gentle plains for creative/build servers.",
        "recipe": {"name": "Builder Flatlands", "size": 2000, "seed": 1,
                   "theme": "flatlands"},
    },
]
