"""
Character-level tag database for Roblox clothing metadata.
Each keyword maps to tags specific to that character/person/game.
"""

# ────────────────────────────────────────────────────────────────────────────
# Always added on top of every description
# ────────────────────────────────────────────────────────────────────────────
BASE_TAGS = "roblox robloxoutfit robloxfashion classicclothing robloxclothing robloxstyle cosplay classicshirt classicpants"

# ────────────────────────────────────────────────────────────────────────────
# Per-character / per-keyword specific tags
# Key: lowercase, no spaces version of the keyword
# ────────────────────────────────────────────────────────────────────────────
CHARACTER_TAGS: dict[str, str] = {

    # ── NARUTO UNIVERSE ──────────────────────────────────────────────────────
    "naruto": "naruto uzumaki narutoshippuden konoha hokage rasengan kurama ninetails baryon sage sagemode leaf village minato hinata boruto shinobi ninja jiraiya tsunade",
    "sasuke": "sasuke uchiha sharingan mangekyou rinnegan chidori cursemark avenger itachi madara akatsuki konoha naruto boruto uchiha",
    "itachi": "itachi uchiha sharingan mangekyou akatsuki susanoo tsukuyomi amaterasu crow genjutsu anbu konoha sasuke",
    "kakashi": "kakashi hatake copyninja sharingan lightning chidori anbu sixthhokage naruto sasuke sakura team7",
    "sakura": "sakura haruno byakugou medic team7 naruto sasuke kakashi tsunade kunoichi leaf konoha",
    "hinata": "hinata hyuga byakugan gentle fist neji naruto konoha kunoichi tentenchu",
    "gaara": "gaara sabaku sand gourd kazekage shukaku naruto desert sunagakure",
    "jiraiya": "jiraiya sannin toad sage hermit pervy naruto tsunade konoha",
    "minato": "minato namikaze yellowflash tobirama fourthhokage space-time naruto kurama",
    "obito": "obito uchiha tobi madara ten-tails rinnegan sharingan kakashi akatsuki",
    "madara": "madara uchiha rinnegan susanoo ten-tails eternal hashirama akatsuki",
    "boruto": "boruto uzumaki jougan karma naruto sarada mitsuki konoha next generation",

    # ── JJK (JUJUTSU KAISEN) ─────────────────────────────────────────────────
    "gojo": "gojo satoru gojosensei sixeyes infinity void limitless jjk jujutsukaisen blindfold cursed higuruma yuji megumi nobara",
    "yuji": "yuji itadori jjk jujutsukaisen sukuna divergent fist mahoraga gojo megumi nobara first year",
    "megumi": "megumi fushiguro jjk jujutsukaisen tenshi-dori mahoraga divine dogs shadow gojo yuji nobara shikigami",
    "nobara": "nobara kugisaki jjk jujutsukaisen straw doll resonance yuji megumi gojo first year hammer nails",
    "sukuna": "sukuna jjk jujutsukaisen ryomen fingerlickers cursed malevolent shrine cleave dismantle yuji",
    "geto": "geto suguru jjk jujutsukaisen cursed spirit manipulation haibara gojo nanami",
    "nanami": "nanami kento jjk jujutsukaisen ratio overtime gojo yuji blade overtime",
    "toji": "toji fushiguro jjk jujutsukaisen slayer blade megumi zenin clan",
    "choso": "choso jjk jujutsukaisen blood manipulation piercing blood supernova yuji kechizu eso",

    # ── ONE PIECE ────────────────────────────────────────────────────────────
    "luffy": "luffy straw hat onepiece gear5 gearfifth joyboy nika gum gum nami zoro sanji pirate king rubberman gomu",
    "zoro": "zoro roronoa onepiece swordsman santoryu onigiri wano ashura mihawk haki straw hat",
    "nami": "nami onepiece navigator clima-tact orangetang straw hat bellemere arlong",
    "sanji": "sanji onepiece cook diable jambe ifrit judge strawhats judge wano kicking-style",
    "usopp": "usopp onepiece sniper sogeking strawhats syrup village kaya",
    "robin": "robin onepiece archaeologist poneglyph ohara nico devil fruit bloom",
    "ace": "ace portgas d onepiece fire fist whitebeard mera mera second division commander",
    "shanks": "shanks onepiece yonko redshirts haoshoku haki emperor arm",
    "law": "law trafalgar onepiece warlord ope ope heart pirates room shambles",
    "chopper": "chopper onepiece doctor drum island rumble ball hito hito doctorine",

    # ── DEMON SLAYER ─────────────────────────────────────────────────────────
    "tanjiro": "tanjiro kamado demonslayer water breathing hinokami kagura muzan star nezuko zenitsu inosuke hashira",
    "nezuko": "nezuko kamado demonslayer blood demon art bamboo muzan tanjiro",
    "zenitsu": "zenitsu agatsuma demonslayer thunder breathing godspeed sparrow tanjiro nezuko inosuke",
    "inosuke": "inosuke hashibira demonslayer beast breathing boar twin swords tanjiro zenitsu",
    "rengoku": "rengoku kyojuro demonslayer flame breathing hashira uppermoonfour akaza",
    "tengen": "tengen uzui demonslayer sound breathing hashira entertainment district",
    "giyu": "giyu tomioka demonslayer water breathing hashira sabito makomo",
    "muzan": "muzan kibutsuji demonslayer twelvedemonic moons uppermoon control blooddemon biwa",
    "akaza": "akaza demonslayer uppermoon three compass needle destructiondeath rengoku percussion",
    "gyomei": "gyomei himejima demonslayer stone breathing hashira urokodaki",

    # ── ATTACK ON TITAN ──────────────────────────────────────────────────────
    "eren": "eren yeager attackontitan aot founding shingeki founding titan rumbling mikasa armin",
    "mikasa": "mikasa ackerman attackontitan aot ackerman clan blades 3dmg eren armin",
    "levi": "levi ackerman attackontitan aot captain humanity blades 3dmg survey corps",
    "armin": "armin arlert attackontitan aot colossaltitan strategist colossal titan",
    "reiner": "reiner braun attackontitan aot armortitan warriors 104th",
    "zeke": "zeke yeager attackontitan aot warbeast thunder spear roar",

    # ── MY HERO ACADEMIA ─────────────────────────────────────────────────────
    "deku": "deku izuku midoriya myheroacademia mha oneforall smash plus ultra all might ua quirk",
    "bakugo": "bakugo katsuki myheroacademia mha explosion howitzer king explosion murder ua deku",
    "todoroki": "todoroki shoto myheroacademia mha half-hot half-cold endeavor ice fire ua",
    "allmight": "all might myheroacademia mha symbol peace one for all united states of smash",
    "ochaco": "ochaco uraraka myheroacademia mha zero gravity meteor storm ua deku",
    "endeavor": "endeavor myheroacademia mha flamethrower hellflame number one pro hero todoroki",

    # ── DRAGON BALL ──────────────────────────────────────────────────────────
    "goku": "goku dragonball dbz dbs kakarot saiyan ultra instinct ssgb super goku kamehameha kaioken vegeta",
    "vegeta": "vegeta dragonball dbz prince of saiyans final flash super galick gun bulma goku",
    "gohan": "gohan dragonball dbz half-saiyan ultimate beast goku chichi videl",
    "broly": "broly dragonball dbz legendary saiyan dbs wrath state kakarot paragus cheelai lemo",
    "piccolo": "piccolo dragonball dbz namekian special beam cannon god gohan goku",
    "frieza": "frieza dragonball dbz emperor galaxy golden black emperor revival goku vegeta",
    "beerus": "beerus dragonball dbz dbs god of destruction hakai whis universe seven goku",
    "cell": "cell dragonball dbz perfect form gohan android 17 18 android saga kamehameha",

    # ── ONE PUNCH MAN ────────────────────────────────────────────────────────
    "saitama": "saitama onepunchman opm serious punch bald cape baldcapecrush genos king hero",
    "genos": "genos onepunchman opm cyborg s-class incineration cannon upgrade saitama sonic",

    # ── CHAINSAW MAN ─────────────────────────────────────────────────────────
    "denji": "denji chainsawman csm chainsaw devil hybrid makima aki power beam",
    "makima": "makima chainsawman csm control devil primal fear dogs denji power",
    "power": "power chainsawman csm blood fiend hammer bat blood manipulation denji makima",
    "aki": "aki hayakawa chainsawman csm fox devil future devil sword denji makima",

    # ── BLEACH ───────────────────────────────────────────────────────────────
    "ichigo": "ichigo kurosaki bleach substitute shinigami bankai tensa zangetsu hollow vizard fullbring soul reaper",
    "rukia": "rukia kuchiki bleach shinigami sode no shirayuki dance kido soul society ichigo",
    "aizen": "aizen sosuke bleach traitor hogyoku kyoka suigetsu illusion espada",
    "ulquiorra": "ulquiorra cifer bleach espada hierro nihility ressurecion segunda etapa",

    # ── HUNTER X HUNTER ──────────────────────────────────────────────────────
    "gon": "gon freecss hunterxhunter hxh janken jan ken zetsu ren hatsu killua zushi nen",
    "killua": "killua zoldyck hunterxhunter hxh godspeed lightning electricity nen assassin gon",
    "kurapika": "kurapika hunterxhunter hxh scarlet eyes kurta clan chain jail emperor time",
    "hisoka": "hisoka morrow hunterxhunter hxh bungee gum clown magician transmutation",
    "meruem": "meruem chimera ant hunterxhunter hxh king komugi neferpitou shaiapouf",

    # ── FAIRY TAIL ────────────────────────────────────────────────────────────
    "natsu": "natsu dragneel fairytail fire dragon slayer happy igneel erza lucy gray guild",
    "erza": "erza scarlet fairytail titania requip armor sword guild natsu lucy gray",
    "gray": "gray fullbuster fairytail ice make devil slayer deliora lyon natsu erza lucy",
    "lucy": "lucy heartfilia fairytail celestial wizard zodiac keys aquarius natsu erza guild",

    # ── SWORD ART ONLINE ─────────────────────────────────────────────────────
    "kirito": "kirito kazuto kirigaya swordartonline sao aincrad black swordsman dual wield asuna",
    "asuna": "asuna yuuki swordartonline sao lightning flash rapier fairy dance kirito",

    # ── RE:ZERO ───────────────────────────────────────────────────────────────
    "rem": "rem rezero reborn emilia subaru maid twin horn oni blue hair",
    "emilia": "emilia rezero half-elf puck subaru rem beatrice silver hair spirit",

    # ── EVANGELION ────────────────────────────────────────────────────────────
    "rei": "rei ayanami evangelion neon genesis eva unit00 shinji gendo yui",
    "asuka": "asuka langley evangelion neon genesis eva unit02 pilot baka pilot",

    # ── FULLMETAL ALCHEMIST ───────────────────────────────────────────────────
    "edward": "edward elric fullmetalalchemist fma automail philosopher stone equivalent exchange alphonse",
    "alphonse": "alphonse elric fullmetalalchemist fma armor philosopher stone edward alchemy",
    "roy": "roy mustang fullmetalalchemist fma flame alchemist colonel gloves edward",

    # ── JOJO'S BIZARRE ADVENTURE ──────────────────────────────────────────────
    "jotaro": "jotaro kujo jojo bizarre adventure star platinum ora dio part3 stardust crusaders",
    "giorno": "giorno giovanna jojo bizarre adventure gold experience requiem part5 vento aureo",
    "josuke": "josuke higashikata jojo bizarre adventure crazy diamond part4 diamond is unbreakable",
    "dio": "dio brando jojo bizarre adventure the world part1 phantom blood vampire za warudo",

    # ── SLIME ISEKAI ─────────────────────────────────────────────────────────
    "rimuru": "rimuru tempest slimeisekai tensura great sage ifrit veldora milim goblin",

    # ── DEMON SLAYER EXTRAS ───────────────────────────────────────────────────
    "douma": "douma demonslayer uppermoon two blood demon art lotus ice flower",
    "kokushibo": "kokushibo demonslayer uppermoon one breath of moon yoriichi michikatsu",

    # ═══════════════════════════════════════════════════════════════════════════
    # MARVEL CHARACTERS
    # ═══════════════════════════════════════════════════════════════════════════
    "spiderman": "spiderman spidey peter parker miles morales webslinger marvel amazing spider-sense spiderverse venom avengers",
    "ironman": "ironman tony stark marvel avengers arc reactor suit of armor repulsor infinity war",
    "thor": "thor odinson marvel avengers asgard mjolnir stormbreaker lightning thunder loki",
    "hulk": "hulk bruce banner marvel avengers gamma radiation smash green strongest",
    "blackwidow": "blackwidow natasha romanoff marvel avengers spy red room widow's bite",
    "captainamerica": "captain america steve rogers marvel avengers shield vibranium peggy avengers",
    "deadpool": "deadpool wade wilson marvel merc mouth chimichanga regeneration katana x-men",
    "wolverine": "wolverine logan xmen marvel adamantium claws berserker cyclops storm",
    "venom": "venom eddie brock marvel symbiote spider-man carnage lethal protector",
    "thanos": "thanos marvel infinity gauntlet infinity stones avengers snap grimoire",
    "spiderverse": "spiderverse spiderman miles morales gwen spider-gwen peni parker noir marvel",

    # ═══════════════════════════════════════════════════════════════════════════
    # DC CHARACTERS
    # ═══════════════════════════════════════════════════════════════════════════
    "batman": "batman bruce wayne dc gotham dark knight joker batarang cowl arkham justice league",
    "superman": "superman clark kent dc metropolis krypton laser cape strength justice man of steel",
    "joker": "joker dc batman gotham arkham criminal chaos why so serious card",
    "harleyquinn": "harley quinn dc joker batman arkham gotham mad love doctor quinzel carnival",
    "wonderwoman": "wonder woman diana dc amazons themyscira lasso justice league",
    "flash": "flash barry allen dc speed force fastest man alive justice league",

    # ═══════════════════════════════════════════════════════════════════════════
    # GAMES
    # ═══════════════════════════════════════════════════════════════════════════
    "minecraft": "minecraft steve creeper diamond pickaxe steve alex ender dragon notch mojang survival craft blocks",
    "fortnite": "fortnite epic games battle royale building default dance skull trooper",
    "valorant": "valorant riot games tactical shooter agent spike jett reyna killjoy phoenix sage sentinel",
    "jett": "jett valorant korean agent wind dash cloudwalk sage killjoy sage",
    "jinx": "jinx arcane league of legends powder lol vi caitlyn zaun shimmer powder",
    "vi": "vi arcane league of legends vander piltover caitlyn jinx shimmer",
    "roblox": "roblox noob builderman adopt me pet simulator mm2 bloxburg brookhaven",
    "minecraft steve": "minecraft steve creeper diamond pickaxe enderman blocks survival craft",
    "master chief": "masterchief halo spartan odst covenant unsc xbox 343",
    "kratos": "kratos godofwar greek norse spartan ragnarok blades of chaos atreus",
    "link": "link zelda hylian triforce sword shield master sword ocarina botw totk",
    "mario": "mario supermario luigi bowser peach mushroom kingdom star nintendo",
    "sonic": "sonic sega hedgehog rings chaos emerald knuckles tails shadow amy rouge",
    "genji": "genji shimada overwatch cyborg ninja dragon blade shimadastrike hanzo",
    "hanzo": "hanzo shimada overwatch archer dragon genji scatter arrow dragonstrike",

    # ═══════════════════════════════════════════════════════════════════════════
    # SPORTS / ATHLETES
    # ═══════════════════════════════════════════════════════════════════════════
    "ronaldo": "ronaldo cr7 christianoronaldo siuu portugal real madrid manchester united al nassr juventus football soccer",
    "messi": "messi leomessi argentina psg barcelona inter miami football soccer goat copa",
    "neymar": "neymar neymanjr brazil psg barcelona santos football soccer skill dribble",
    "mbappe": "mbappe kylian france psg real madrid speed skill football soccer worldcup",
    "lebron": "lebron james lebron lakers nba basketball king akron cavaliers miami heat",
    "kobe": "kobe bryant mamba blackmamba lakers nba basketball 24 8 forever legend",
    "curry": "curry stephen curry warriors nba basketball splash bros three-pointer under armour",
    "federer": "federer roger tennis grand slam wimbledon australian open elegance goat",
    "nadal": "nadal rafael tennis clay king french open spain forehand",
    "djokovic": "djokovic novak tennis serbian goat grand slam wimbledon us open",
    "jordan": "jordan michael airjordan mj bulls nba basketball goat chicago bulls 23",
    "mayweather": "mayweather floyd boxing tmt tmoney undefeated money team",
    "tyson": "tyson mike boxing iron heavyweight champion brooklyn baddest man on the planet",

    # ═══════════════════════════════════════════════════════════════════════════
    # GENERIC FALLBACK CATEGORIES
    # ═══════════════════════════════════════════════════════════════════════════
    "_anime":  "anime animegirl animefan jjk naruto demonslayer attackontitan dragonball onepiece myheroacademia",
    "_marvel": "marvel avengers superhero comics spiderman ironman thor hulk xmen",
    "_dc":     "dc batman superman gotham joker wonderwoman flash justice",
    "_games":  "gaming gamer videogames minecraft fortnite valorant overwatch roblox esports",
    "_sports": "sports football soccer basketball nba fifa athlete goal champion",
}

# ────────────────────────────────────────────────────────────────────────────
# Public helper
# ────────────────────────────────────────────────────────────────────────────
def get_tags(keyword: str) -> str:
    """
    Return tags relevant to a keyword.
    1. Try exact match in CHARACTER_TAGS.
    2. Try partial match (keyword is substring of a key, or in a value).
    3. Try genre fallback (_anime, _marvel, _dc, _games, _sports).
    4. Return BASE_TAGS only.
    """
    kw = keyword.lower().strip().replace(" ", "")

    # 1. Exact match
    if kw in CHARACTER_TAGS:
        return f"{CHARACTER_TAGS[kw]}"

    # 2. Partial match – keyword appears inside a key
    for key, tags in CHARACTER_TAGS.items():
        if key.startswith("_"):
            continue
        if kw in key or key in kw:
            return tags

    # 3. Keyword found inside a category's tag string
    for key, tags in CHARACTER_TAGS.items():
        if key.startswith("_"):
            continue
        if kw in tags.lower():
            return tags

    # 4. Genre-level fallback guesses
    anime_hints  = ["anime", "manga", "shonen", "waifu", "jjk", "naruto", "otaku"]
    marvel_hints = ["marvel", "avengers", "mcu", "xmen", "stark", "spider"]
    dc_hints     = ["dc", "batman", "superman", "gotham", "arkham"]
    game_hints   = ["game", "gaming", "fps", "rpg", "mmorpg", "esport", "minecraft", "fortnite"]
    sport_hints  = ["football", "soccer", "basketball", "nba", "nfl", "tennis", "boxing", "mma"]

    kw_raw = keyword.lower()
    if any(h in kw_raw for h in anime_hints):
        return CHARACTER_TAGS["_anime"]
    if any(h in kw_raw for h in marvel_hints):
        return CHARACTER_TAGS["_marvel"]
    if any(h in kw_raw for h in dc_hints):
        return CHARACTER_TAGS["_dc"]
    if any(h in kw_raw for h in game_hints):
        return CHARACTER_TAGS["_games"]
    if any(h in kw_raw for h in sport_hints):
        return CHARACTER_TAGS["_sports"]

    # 5. Unknown – combine all fallbacks
    return " ".join(v for k, v in CHARACTER_TAGS.items() if k.startswith("_"))
