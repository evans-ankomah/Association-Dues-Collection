"""Ghanaian name pools and a generator that keeps given/family names culturally consistent.

Weights lean towards Akan and Fante names, matching UMaT's Western Region location,
with Ewe, Ga-Adangbe and Northern/Muslim names well represented.
"""

ENGLISH_M = ["Emmanuel", "Daniel", "Samuel", "Michael", "Joseph", "Isaac", "Prince", "Richard", "Benjamin",
             "Bernard", "Francis", "Eric", "Felix", "Stephen", "Ebenezer", "Godfred", "Nathaniel", "Derrick",
             "Collins", "Kelvin", "Jeffrey", "Bright", "Justice", "Gideon", "Enoch", "Solomon", "David", "Jonathan",
             "Kenneth", "Desmond", "Clement", "Augustine", "Raymond", "Frederick", "Patrick", "Dominic", "Evans",
             "Philip", "Elvis", "Mark", "Caleb", "Joshua", "Kingsley", "Elijah", "Theophilus", "Silas", "Obed"]
ENGLISH_F = ["Priscilla", "Gifty", "Mercy", "Grace", "Abigail", "Esther", "Linda", "Vida", "Patience", "Jennifer",
             "Rita", "Comfort", "Joyce", "Deborah", "Sandra", "Doris", "Josephine", "Belinda", "Nancy", "Ruth",
             "Freda", "Lydia", "Rebecca", "Hannah", "Juliet", "Phyllis", "Cynthia", "Evelyn", "Bernice", "Matilda",
             "Gloria", "Naomi", "Judith", "Barbara", "Dorcas", "Eunice", "Sarah", "Rosemond", "Millicent"]

GROUPS = {
    "akan": {
        "weight": 35,
        "day_m": ["Kwame", "Kofi", "Kwabena", "Kwaku", "Yaw", "Kwasi", "Kwadwo", "Kojo", "Kwesi"],
        "day_f": ["Ama", "Akosua", "Abena", "Adwoa", "Afua", "Yaa", "Akua", "Afia", "Adjoa"],
        "local_m": ["Nana", "Osei", "Nkansah", "Opoku"],
        "local_f": ["Nana", "Serwaa", "Pokuaa", "Konadu", "Agyeiwaa", "Afriyie", "Oforiwaa", "Nyarkoa"],
        "family": ["Mensah", "Owusu", "Boateng", "Asante", "Agyeman", "Amoah", "Osei", "Appiah", "Adjei", "Ofori",
                   "Antwi", "Darko", "Asamoah", "Bonsu", "Frimpong", "Gyamfi", "Kyei", "Opoku", "Sarpong", "Yeboah",
                   "Acheampong", "Amponsah", "Baah", "Danso", "Kusi", "Oppong", "Poku", "Twumasi", "Wiredu", "Asiedu",
                   "Agyei", "Addo", "Ampofo", "Adomako", "Badu", "Boadu", "Duah", "Fosu", "Gyasi", "Manu", "Nyarko",
                   "Obeng", "Owusu-Ansah", "Sarfo", "Kumi", "Nyamekye", "Ansah", "Takyi", "Bediako", "Boakye"],
        "english_share": 0.55,
    },
    "fante_western": {
        "weight": 22,
        "day_m": ["Kwesi", "Kobina", "Kweku", "Ekow", "Kojo", "Kwamena", "Fiifi", "Paa Kwesi", "Kwame"],
        "day_f": ["Esi", "Efua", "Araba", "Aba", "Ekua", "Adwoa", "Ama", "Abena", "Efua"],
        "local_m": ["Nana"],
        "local_f": ["Nana", "Maame"],
        "family": ["Arthur", "Quansah", "Eshun", "Aidoo", "Ackah", "Annan", "Bentil", "Eduful", "Essel", "Ghartey",
                   "Hagan", "Koomson", "Kwofie", "Quayson", "Sam", "Yawson", "Abban", "Amissah", "Arhin", "Baidoo",
                   "Brew", "Coffie", "Dadzie", "Ennin", "Forson", "Mbeah", "Nketsiah", "Otoo", "Prah", "Quaicoe",
                   "Cudjoe", "Assan", "Cobbinah", "Blay", "Erzuah", "Kaku", "Andoh", "Eghan", "Mensah", "Bonney"],
        "english_share": 0.6,
    },
    "ewe": {
        "weight": 15,
        "day_m": ["Kofi", "Kodzo", "Kwami", "Yao", "Kosi", "Komla", "Kwaku"],
        "day_f": ["Afi", "Adzo", "Abla", "Yawa", "Akos", "Ama"],
        "local_m": ["Selasi", "Elikem", "Edem", "Mawuli", "Senyo", "Delali", "Etornam", "Sedem", "Dodzi", "Kekeli",
                    "Worlali", "Eyram"],
        "local_f": ["Elinam", "Esinam", "Dzifa", "Enyonam", "Sena", "Makafui", "Mawusi", "Akpene", "Yayra", "Dela",
                    "Eyram", "Kafui", "Sedinam"],
        "family": ["Agbenyega", "Ahiable", "Amegah", "Atsu", "Dogbe", "Dzidzornu", "Fiagbe", "Gbedemah", "Kpodo",
                   "Kumordzie", "Ladzekpo", "Sedziafa", "Agbozo", "Akpabli", "Adzraku", "Avornyo", "Kuwornu",
                   "Gadzekpo", "Akakpo", "Amenyo", "Agbeko", "Dzokoto", "Tsikata", "Agbemenya", "Klutse", "Afenyo",
                   "Nyamadi", "Amedzro", "Kpeglo", "Gbeku"],
        "english_share": 0.5,
    },
    "ga_adangbe": {
        "weight": 10,
        "day_m": ["Kpakpo", "Ayi", "Lante", "Odartey"],
        "day_f": ["Dedei", "Korkor", "Adoley", "Ayeley", "Adjeley"],
        "local_m": ["Nii Armah", "Nii Odartey", "Nii Ayitey", "Nii Lante"],
        "local_f": ["Naa Adjeley", "Naa Dedei", "Naa Korkoi", "Naa Ayeley"],
        "family": ["Quaye", "Tetteh", "Lamptey", "Nortey", "Quarshie", "Laryea", "Ankrah", "Aryee", "Kotey", "Odoi",
                   "Ashitey", "Okine", "Adjetey", "Nartey", "Tagoe", "Sowah", "Armah", "Oblitey", "Odartey", "Ofoe",
                   "Mensah", "Narh", "Tettey", "Abbey", "Allotey"],
        "english_share": 0.65,
    },
    "northern": {
        "weight": 18,
        "day_m": ["Abdul-Rahman", "Mohammed", "Ibrahim", "Yakubu", "Issah", "Abdul-Rashid", "Mustapha", "Fuseini",
                  "Sulemana", "Rashid", "Abdul-Karim", "Awal", "Shamsudeen", "Mubarak", "Haruna", "Nurudeen"],
        "day_f": ["Fatima", "Rahinatu", "Aisha", "Zainab", "Hajara", "Mariam", "Salamatu", "Amina", "Fuseina",
                  "Barikisu", "Habiba", "Rashida", "Sadia", "Mansura"],
        "local_m": ["Bayor", "Dery", "Kuuire", "Atanga", "Ayamga", "Akolgo"],
        "local_f": ["Ayamba", "Azumah", "Ayine"],
        "family": ["Iddrisu", "Abubakar", "Alhassan", "Mahama", "Yakubu", "Issahaku", "Seidu", "Mohammed", "Fuseini",
                   "Salifu", "Abdulai", "Sulemana", "Musah", "Bawa", "Dramani", "Zakaria", "Mumuni", "Osman",
                   "Tahiru", "Yahaya", "Bayor", "Dery", "Kuuire", "Ziem", "Akanbong", "Ayamga", "Atanga", "Akolgo",
                   "Azure", "Atampugre", "Naab", "Bawah", "Gariba", "Adams"],
        "english_share": 0.4,
    },
}


class NameGen:
    def __init__(self, rng):
        self.rng = rng
        self._groups = list(GROUPS)
        self._weights = [GROUPS[g]["weight"] for g in self._groups]

    def person(self, female):
        """Return (given_name, middle_name or None, family_name)."""
        rng = self.rng
        g = GROUPS[rng.choices(self._groups, self._weights)[0]]
        local = g["local_f"] if female else g["local_m"]
        day = g["day_f"] if female else g["day_m"]
        english = ENGLISH_F if female else ENGLISH_M
        if rng.random() < g["english_share"]:
            given = rng.choice(english)
            middle = rng.choice(day + local) if rng.random() < 0.7 else None
        else:
            given = rng.choice(day + local)
            middle = rng.choice(english) if rng.random() < 0.25 else None
        family = rng.choice(g["family"])
        if middle == given:
            middle = None
        return given, middle, family
