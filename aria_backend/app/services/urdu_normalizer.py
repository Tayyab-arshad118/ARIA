import re
import unicodedata

# Urdu's 0–99 forms are irregular; use explicit words rather than English-style composition.
SMALL = ("صفر ایک دو تین چار پانچ چھ سات آٹھ نو دس گیارہ بارہ تیرہ چودہ پندرہ سولہ سترہ اٹھارہ انیس "
         "بیس اکیس بائیس تئیس چوبیس پچیس چھبیس ستائیس اٹھائیس انتیس تیس اکتیس بتیس تینتیس چونتیس پینتیس چھتیس سینتیس اڑتیس انتالیس "
         "چالیس اکتالیس بیالیس تینتالیس چوالیس پینتالیس چھیالیس سینتالیس اڑتالیس انچاس پچاس اکیاون باون ترپن چون پچپن چھپن ستاون اٹھاون انسٹھ "
         "ساٹھ اکسٹھ باسٹھ تریسٹھ چونسٹھ پینسٹھ چھیاسٹھ سڑسٹھ اڑسٹھ انہتر ستر اکہتر بہتر تہتر چوہتر پچھتر چھہتر ستتر اٹھہتر اناسی "
         "اسی اکیاسی بیاسی تراسی چوراسی پچاسی چھیاسی ستاسی اٹھاسی نواسی نوے اکانوے بانوے ترانوے چورانوے پچانوے چھیانوے ستانوے اٹھانوے ننانوے").split()


def integer_words(value: int) -> str:
    if value < 100:
        return SMALL[value]
    for size, name in ((10**7, "کروڑ"), (10**5, "لاکھ"), (1000, "ہزار"), (100, "سو")):
        if value >= size:
            whole, rest = divmod(value, size)
            return integer_words(whole) + " " + name + (" " + integer_words(rest) if rest else "")
    raise AssertionError("unreachable")


def number_words(match):
    token = "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in match.group())
    negative = token.startswith("-")
    token = token.lstrip("+-").replace(",", "")
    parts = re.split(r"[.٫]", token, maxsplit=1)
    whole = parts[0]
    # Preserve leading zeros/long identifiers as spoken individual digits.
    if len(whole) > 12 or (len(whole) > 1 and whole.startswith("0")):
        spoken = " ".join(SMALL[int(c)] for c in whole)
    else:
        spoken = integer_words(int(whole))
    if len(parts) > 1:
        spoken += " اعشاریہ " + " ".join(SMALL[int(c)] for c in parts[1])
    return ("منفی " if negative else "") + spoken


def normalize_urdu(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(str.maketrans({
        "ي": "ی", "ى": "ی", "ك": "ک", "ة": "ہ", "ۀ": "ہ", "ه": "ہ", "ـ": "",
        "أ": "ا", "إ": "ا", "ٱ": "ا",
        "\u200c": "", "\u200d": "", "\ufeff": "", "\u200e": "", "\u200f": "",
    }))
    # Preserve hamza-bearing letters; discard combining vocalization marks.
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[+-]?\d+(?:,\d{3})*(?:[.٫]\d+)?", number_words, text)
    text = text.translate(str.maketrans({",": "،", "?": "؟", ".": "۔", ";": "؛"}))
    return "\n".join(re.sub(r"[^\S\n]+", " ", line).strip() for line in text.splitlines()).strip()
