from string import ascii_letters, digits, punctuation


CHARSETS = {

    "classic":
        "@%#*+=-:_|/\\. ",

    "dense":
        ascii_letters + digits + punctuation + " ",

    "blocks":
        "█▓▒░ ",

    "matrix":
        "@#01",

    "hex":
        "0123456789ABCDEF",

    "binary":
        "01"

}
