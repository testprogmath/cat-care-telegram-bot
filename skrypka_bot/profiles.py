import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Bands:
    unit: str
    target_low: float
    target_high: float
    alarm: float
    severe: float
    critical: float
    critical_note: str
    streak_days: int = 1


@dataclass(frozen=True)
class Profile:
    """One animal: how to parse for it, what to aim for, and what to call it outside.

    `key` is internal. It names the profile in configuration, in `chats.profile` and on
    the command line, and renaming it is an ordinary refactor.

    `subject_id` is not. It is the stable identifier this animal has in external data
    contracts, it is stored on every event, and downstream systems key their own records
    on it. Once CareDay records have been consumed anywhere, changing a subject_id is a
    migration on both sides, never a rename. The two may hold the same string; that is a
    coincidence of today's naming and not a rule.
    """

    key: str
    subject_id: str
    name: str
    title_markers: tuple[str, ...]
    aliases: tuple[str, ...]
    self_label: str
    verb_received: str
    subject: str
    feeding_field: str
    feeding_products: str
    toilet_notes: str
    water_goal_ml: float
    kcal_goal: float
    kcal_bands: Bands | None = None
    water_bands: Bands | None = None


def _goal(key: str, field: str, default: float) -> float:
    return float(os.environ.get(f"{key.upper()}_{field}", default))


_ROYAL_CANIN_SENSORY = (
    'Royal Canin Sensory Smell (кусочки в соусе, пауч 85 г; в чате — "Sensory Smell", '
    '"сенсори смелл", "RC Sensory") — по этикетке 852 ккал/кг и влажность 79.6%: '
    'kcal = граммы × 0.852, amount_ml равен граммам, liquid true, water_fraction 0.796.\n'
    'Royal Canin Sensory Taste (кусочки в соусе, пауч 85 г; "Sensory Taste", "сенсори тейст") '
    '— по этикетке 861 ккал/кг и влажность 79.5%: kcal = граммы × 0.861, amount_ml равен '
    'граммам, liquid true, water_fraction 0.795.\n'
    'Royal Canin Sensory Feel (кусочки в соусе, пауч 85 г; "Sensory Feel", "сенсори фил") — '
    'по этикетке 855 ккал/кг и влажность 79.6%: kcal = граммы × 0.855, amount_ml равен '
    'граммам, liquid true, water_fraction 0.796. Если сказано просто "Sensory" без Smell, '
    'Taste или Feel, считай по Smell: все три почти одинаковы.\n'
)


SKRIPA = Profile(
    key="skripa",
    subject_id="skripa",
    name="Скрипа",
    title_markers=("скрип", "скрып"),
    aliases=("скрипа", "скрипка", "скрыпка"),
    self_label="сама",
    verb_received="получила",
    subject=(
        'Ты разбираешь сообщения из семейного чата, где ведётся дневник ухода за кошкой по имени '
        'Скрипа (Скрипка, Скрыпка). В доме есть и другие животные (например, коты Кася и Чипуня) '
        '— их действия НЕ записывай. Действия людей (хозяев) тоже не записывай, если это не уход '
        'за Скрипой. Местоимения "она", "кошечка" без уточнения относятся к Скрипе.'
    ),
    feeding_field=(
        'feeding — способ кормления: "tube", если корм дан через зонд/стому '
        '(Royal Canin Recovery Liquid и вообще любой корм, количество которого указано в мл, — '
        'это всегда зонд, если явно не сказано иное); "self", если ела сама (сухой корм, снеки, '
        'liquid snack, еда из миски). Явное указание в тексте ("через зонд", "через стому", '
        '"сама съела") важнее этих правил. amount_ml — объём корма в миллилитрах, если количество '
        'указано в мл (важно для учёта кормлений через зонд).'
    ),
    feeding_products=(
        'Trovet CCL Recovery Liquid (он же Trovet Recovery Liquid, Trovet CCL, Critical Care '
        'Liquid) — готовый жидкий лечебный корм для зонда, как и Royal Canin Recovery Liquid, но '
        'менее калорийный: 0.69 ккал/мл против 1 ккал/мл. Считай: amount_ml равен объёму, '
        'kcal = объём × 0.69, feeding "tube", liquid true, water_fraction 0.87. Не путай его с '
        'Royal Canin: если назван Trovet, бери 0.69 ккал/мл.\n'
        'Отдельно про ДОМАШНИЙ жидкий корм для зонда: паштет Monge Vet Solutions Gastrointestinal, '
        'разведённый водой. В сообщении о кормлении указанный объём — это ВСЕГДА объём уже готовой '
        'разведённой смеси, а не паштета до разведения. Считай его так: amount_ml равен этому '
        'объёму, kcal = объём × 0.65, feeding "tube", liquid true, water_fraction 0.875.\n'
        'Узнать этот корм можно по формулировкам "такой корм", "домашний корм в зонд", '
        '"разведённый паштет", "взбитый паштет", "паштет с водой", "корм из паштета", а также по '
        'прямому упоминанию паштета Monge (Vet Solutions, Gastrointestinal) через зонд. Любой '
        'паштет, введённый через зонд, — это он: считай по правилу выше, а не как пауч (0.79). '
        'Не путай с Royal Canin Recovery Liquid (1 ккал/мл).\n'
        'Если в том же сообщении названа ещё и вода ("дала 50 мл разведённого паштета и 11 мл '
        'воды", "48 мл такого корма и 12 мл воды сверху"), — это ОТДЕЛЬНАЯ вода: промывка зонда '
        'после кормления, а не часть смеси. Создай на неё событие water с этим объёмом. Пример: '
        '"дала 50мл разведенного паштета Monge и 11мл воды" → food 50 мл / 32.5 ккал / '
        'water_fraction 0.875 и water 11 мл.\n'
        'ВАЖНО: приготовление смеси — это НЕ кормление. Если сообщение только про то, что корм '
        'сделан, разведён, набран в шприц или сколько его получилось ("сделала корм для зонда", '
        '"развела 50 г паштета 50 мл воды", "из 50 г корма и 50 мл воды выходит 80 мл", "стоит в '
        'шприце"), не создавай ни food, ни water — верни пустой список. Здесь названные граммы '
        'паштета и миллилитры воды — это рецепт, а не приём. События создавай только когда корм '
        'реально введён кошке: "дала", "ввела", "залила", "скормила", "прошло через зонд".\n'
        'Если корм введён через зонд/стому, но продукт не назван ("дала через зонд", "залила в '
        'зонд 30 мл") — это всегда Royal Canin Recovery Liquid: укажи его в description и оцени '
        'kcal из объёма (около 1 ккал/мл).\n'
        'Если ела сама сухой корм ("сухарики", "сухой корм") без названия — по умолчанию это '
        'Purina One для стерилизованных (около 3.7 ккал/г): подставь название и оцени kcal по '
        'СЪЕДЕННОМУ количеству. "Доесть"/"доела" — это тот же корм, что и раньше (обычно сухой '
        'Purina One), отдельный небольшой приём. Учитывай именно съеденное, а не '
        'насыпанное/предложенное. Для сухого корма и снеков, которые кошка ест сама, глаголы '
        '"дала", "насыпала", "положила", "предложила", "принесла" означают, что корм только '
        'предложен: это НЕ приём пищи, событие food не создавай вообще. Примеры, из которых '
        'событие НЕ создаётся: "насыпала 12 г", "Дала 10гр сухариков". Приём — это "съела 6 г", '
        '"доела", "поела". Для зонда наоборот: "дала 30 мл через зонд", "залила 40 мл" — это '
        'фактическое введение, событие создавай. Если сказано, что кошка поела, но известно '
        'только насыпанное количество, а сколько съедено — нет, создай событие и оставь '
        'количество и kcal пустыми.\n'
        'Purina One Bifensis с лососем (zalm, "Purina One zalm", "Bifensis") — сухой корм, '
        '3.87 ккал/г: kcal = граммы × 3.87 по СЪЕДЕННОМУ количеству, liquid false, '
        'amount_ml и water_fraction не заполняй.\n'
        + _ROYAL_CANIN_SENSORY +
        'Hill\'s Prescription Diet i/d Digestive Care, СУХОЙ — по этикетке 3934 ккал/кг: '
        'kcal = граммы × 3.934, liquid false, amount_ml и water_fraction не заполняй. Любое '
        '"Digestive Care", "GastroCare", "Intestinal Care", "i/d", "айди", "Hills" про '
        'СУХОЙ корм — всегда он, даже если в сообщении написано "Royal Canin". Если количество '
        'названо ШТУКАМИ ("60 сухариков Hills", "съела штук 20 Digestive Care"), пересчитай в '
        'граммы: 18 сухариков = 4 г, то есть 0.222 г за штуку (взвешено дома). 60 сухариков = '
        '13.3 г = 52 ккал. Штуки — это НЕ граммы, напрямую их не приравнивай. Пересчёт по '
        'штукам действует только для этого корма: у Purina One вес гранулы не взвешен.\n'
        'Про Felix Soup: если сказано, что она ела или лизала, но не сказано, тронула ли '
        'кусочки, считай, что выпила только бульон: она обычно вылизывает жидкость и кусочки '
        'оставляет.'
    ),
    toilet_notes=(
        ' У Скрипы есть жёлтый коврик, на котором она лежит: "сходила на жёлтый коврик" означает, '
        'что она подошла туда и легла.'
    ),
    water_goal_ml=_goal("skripa", "WATER_GOAL_ML", 340),
    kcal_goal=_goal("skripa", "KCAL_GOAL", 250),
    kcal_bands=Bands(
        unit="ккал",
        target_low=250,
        target_high=250,
        alarm=200,
        severe=150,
        critical=110,
        critical_note="веский аргумент за трубку",
        streak_days=2,
    ),
    water_bands=Bands(
        unit="мл",
        target_low=320,
        target_high=370,
        alarm=250,
        severe=200,
        critical=150,
        critical_note="не ждать следующего дня",
    ),
)


CHIPUNYA = Profile(
    key="chipunya",
    subject_id="chipunya",
    name="Чипуня",
    title_markers=("чипун", "чип"),
    aliases=("чипуня", "чип", "чипун"),
    self_label="сам",
    verb_received="получил",
    subject=(
        'Ты разбираешь сообщения из семейного чата, где ведётся дневник ухода за КОТОМ по имени '
        'Чипуня (Чип, Чипун) — это мальчик. В доме есть и другие животные (например, кошка Скрипа '
        'и кот Кася) — их действия НЕ записывай. Действия людей (хозяев) тоже не записывай, если '
        'это не уход за Чипуней. Местоимения "он", "котик" без уточнения относятся к Чипуне. '
        'В правилах и примерах ниже животное местами названо кошкой в женском роде — это лишь '
        'образцы формулировок, субъект дневника всё равно Чипуня.'
    ),
    feeding_field=(
        'feeding — способ кормления: у Чипуни НЕТ зонда, он ест сам, поэтому по умолчанию всегда '
        '"self". "tube" ставь только если в сообщении прямо сказано про зонд или стому. '
        'amount_ml — объём корма в миллилитрах, если количество указано в мл; для влажного корма '
        'в граммах считай 1 г ≈ 1 мл.'
    ),
    feeding_products=(
        'Сухой корм без названия ("сухарики", "сухой корм") считай по 3.7 ккал/г: оцени kcal по '
        'СЪЕДЕННОМУ количеству, название не выдумывай. Для остального корма по умолчанию ничего '
        'не подставляй: если продукт не назван, оставь name и kcal пустыми, не гадай.\n'
        'Royal Canin для котят (Kitten, Kitten Instinctive — пауч 85 г, кусочки в соусе) — по '
        'этикетке 952 ккал/кг и влажность 78.2%. Считай: kcal = граммы × 0.952, amount_ml равен '
        'граммам, liquid true, water_fraction 0.782. Половина пакетика — это около 42 г, но если '
        'в сообщении названо своё количество ("около 40 г"), бери его. Узнать корм можно по '
        '"Royal Canin для котят", "RC Kitten", "жидкий корм для котят", "кусочки в соусе для '
        'котят".\n'
        'Royal Canin Digestive Care (пауч 85 г, кусочки в соусе) — по этикетке 788 ккал/кг и '
        'влажность 80%. Считай: kcal = граммы × 0.79, amount_ml равен граммам, liquid true, '
        'water_fraction 0.8. Узнать корм можно по "Royal Canin Digestive Care", "RC Digestive '
        'Care", "дайджестив", "корм для пищеварения", "корм для какания", а также по "жидкий '
        'корм" без другого названия. Половина пауча — это около 42 г, но если в сообщении '
        'названо своё количество ("около 40 г"), бери его.\n'
        'Royal Canin Gastrointestinal, ветеринарный влажный (в чате — "Gastro Intestinal", "GI", '
        'тонкие ломтики в соусе, пауч 85 г) — по этикетке 966 ккал/кг и влажность 79.8%: '
        'kcal = граммы × 0.966, amount_ml равен граммам, liquid true, water_fraction 0.798.\n'
        + _ROYAL_CANIN_SENSORY +
        'Hill\'s Prescription Diet i/d Digestive Care, СУХОЙ — по этикетке 3934 ккал/кг: '
        'kcal = граммы × 3.934, liquid false, amount_ml и water_fraction не заполняй. Это тот '
        'самый мешок сухого корма, который стоит дома: любое "Digestive Care", "GastroCare", '
        '"Intestinal Care", "i/d", "айди" про СУХОЙ корм — всегда он, даже если в сообщении '
        'написано "Royal Canin". Название марки в сообщении бывает перепутано, тип корма — нет. '
        'Если количество названо ШТУКАМИ ("32 сухарика", "съел штук 10"), пересчитай в граммы: '
        '18 сухариков = 4 г, то есть 0.222 г за штуку (взвешено дома). 32 сухарика = 7.1 г = '
        '28 ккал. Штуки — это НЕ граммы, напрямую их не приравнивай.\n'
        'Учитывай именно СЪЕДЕННОЕ, а не насыпанное или предложенное. Глаголы "дал", "дала", '
        '"насыпал", "насыпала", "положила", "предложила", "принесла" означают, что корм только '
        'предложен: это НЕ приём пищи, событие food не создавай вообще. Примеры, из которых '
        'событие НЕ создаётся: "насыпала 12 г", "дала 10гр сухариков". Приём — это "съел 6 г", '
        '"доел", "поел". "Доесть"/"доел" — это тот же корм, что и раньше, отдельный небольшой '
        'приём. Если сказано, что кот поел, но известно только насыпанное количество, а сколько '
        'съедено — нет, создай событие и оставь количество и kcal пустыми.'
    ),
    toilet_notes="",
    water_goal_ml=_goal("chipunya", "WATER_GOAL_ML", 340),
    kcal_goal=_goal("chipunya", "KCAL_GOAL", 295),
)


PROFILES = {profile.key: profile for profile in (SKRIPA, CHIPUNYA)}
DEFAULT_KEY = SKRIPA.key


def get(key: str | None) -> Profile:
    return PROFILES.get(key or "", PROFILES[DEFAULT_KEY])


def guess(title: str | None) -> str:
    low = (title or "").lower()
    for profile in PROFILES.values():
        if any(marker in low for marker in profile.title_markers):
            return profile.key
    return DEFAULT_KEY


def resolve(name: str) -> Profile | None:
    low = name.strip().lower()
    for profile in PROFILES.values():
        if low == profile.key or low in profile.aliases:
            return profile
    return None


def names() -> str:
    return ", ".join(profile.name for profile in PROFILES.values())
