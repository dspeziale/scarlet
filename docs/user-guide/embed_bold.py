"""Add the Bold face of PT Sans Narrow as embedded font (docx-js embeds only the Regular face).

Font obfuscation per ECMA-376 Part 1 §17.8.1: XOR of the first 32 bytes with the GUID key.
"""
import re
import sys
import uuid
import zipfile

src, bold_ttf, dst = sys.argv[1:4]
zin = zipfile.ZipFile(src)
files = {n: zin.read(n) for n in zin.namelist()}

guid = str(uuid.uuid4()).upper()
hexs = guid.replace("-", "")
key = bytes(int(hexs[i:i + 2], 16) for i in range(30, -1, -2))  # reversed byte order
data = bytearray(open(bold_ttf, "rb").read())
for i in range(32):
    data[i] ^= key[i % 16]
files["word/fonts/pkm-bold.odttf"] = bytes(data)

rels = files["word/_rels/fontTable.xml.rels"].decode()
rels = rels.replace("</Relationships>",
                    '<Relationship Id="rIdBold1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/font" '
                    'Target="fonts/pkm-bold.odttf"/></Relationships>')
files["word/_rels/fontTable.xml.rels"] = rels.encode()

ft = files["word/fontTable.xml"].decode()
ft = re.sub(r'w:fontKey="(\{[^}]+\})"', lambda m: 'w:fontKey="%s"' % m.group(1).upper(), ft)
ft, n = re.subn(r'(<w:embedRegular [^>]*/>)', r'\1<w:embedBold r:id="rIdBold1" w:fontKey="{%s}"/>' % guid, ft, count=1)
assert n == 1, "embedRegular not found"
files["word/fontTable.xml"] = ft.encode()

ct = files["[Content_Types].xml"].decode()
if 'Extension="odttf"' not in ct:
    ct = ct.replace("<Types ", "<Types ", 1).replace(
        "</Types>", '<Default Extension="odttf" ContentType="application/vnd.openxmlformats-officedocument.obfuscatedFont"/></Types>')
    files["[Content_Types].xml"] = ct.encode()

st = files["word/settings.xml"].decode()
if "embedTrueTypeFonts" not in st:
    # Schema order: displayBackgroundShape, printPostScriptOverText, printFractionalCharacterWidth,
    # printFormsData, embedTrueTypeFonts, ...
    for anchor in ("<w:printFormsData/>", "<w:printFractionalCharacterWidth/>",
                   "<w:printPostScriptOverText/>", "<w:displayBackgroundShape/>"):
        if anchor in st:
            st = st.replace(anchor, anchor + "<w:embedTrueTypeFonts/>", 1)
            break
    else:
        st = re.sub(r"(<w:settings[^>]*>)", r"\1<w:embedTrueTypeFonts/>", st, count=1)
    files["word/settings.xml"] = st.encode()

with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
    for n in zin.namelist():
        zout.writestr(n, files[n])
    if "word/fonts/pkm-bold.odttf" not in zin.namelist():
        zout.writestr("word/fonts/pkm-bold.odttf", files["word/fonts/pkm-bold.odttf"])
print("ok", dst)
