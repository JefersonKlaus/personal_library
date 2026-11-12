import xml.etree.ElementTree as ET

from src.library import opf
from src.library.manager import OPF_META_PREFIX, OPF_TRUSTED_SCHEME

NS = {"dc": "http://purl.org/dc/elements/1.1/", "opf": "http://www.idpf.org/2007/opf"}
OPF = "{http://www.idpf.org/2007/opf}"


def _data(**kwargs) -> opf.OpfData:
    data = dict(title="A & B <Teste>", authors=["Ana Lima", "Rui Dias"], uid_seed="x",
                pubdate="2019-01-01T12:00:00+00:00", languages=["pt"], tags=["importado", " "])
    data.update(kwargs)
    return opf.OpfData(**data)


def test_valid_xml_with_escaping():
    root = ET.fromstring(opf.render_opf(_data(), cover_name="cover.jpg"))
    assert root.find(".//dc:title", NS).text == "A & B <Teste>"
    creators = root.findall(".//dc:creator", NS)
    assert [c.text for c in creators] == ["Ana Lima", "Rui Dias"]
    # Convenção da biblioteca: a ordenação do livro inteiro em todos os autores.
    assert {c.attrib[f"{OPF}file-as"] for c in creators} == {"Lima, Ana & Dias, Rui"}
    assert root.find(".//dc:language", NS).text == "por"
    assert root.find(".//dc:date", NS).text == "2019-01-01T12:00:00+00:00"
    assert [s.text for s in root.findall(".//dc:subject", NS)] == ["importado"]
    assert root.find(f".//{OPF}reference").attrib["href"] == "cover.jpg"


def test_has_the_identifier_the_library_requires():
    """Sem o identificador confiável a biblioteca ignora o OPF inteiro."""
    root = ET.fromstring(opf.render_opf(_data()))
    schemes = {node.attrib.get(f"{OPF}scheme"): (node.text or "").strip()
               for node in root.findall(".//dc:identifier", NS)}
    assert schemes[OPF_TRUSTED_SCHEME] and schemes["uuid"]
    assert root.attrib["unique-identifier"] == "uuid_id"


def test_deterministic_and_omits_unknown_language():
    first = opf.render_opf(_data(languages=[]))
    assert first == opf.render_opf(_data(languages=[]))
    assert "<dc:language>" not in first
    assert opf.language_code("XX") == "xx" and opf.language_code(None) is None


def test_series_publisher_identifiers_and_description():
    root = ET.fromstring(opf.render_opf(_data(
        series="One Punch Man", series_index=18.0, publisher="Panini",
        identifiers={"isbn": "978", OPF_TRUSTED_SCHEME: "ignorado"}, comments="<p>Oi</p>")))
    metas = {m.attrib["name"]: m.attrib["content"] for m in root.findall(f".//{OPF}meta")}
    assert metas[f"{OPF_META_PREFIX}series"] == "One Punch Man"
    assert metas[f"{OPF_META_PREFIX}series_index"] == "18"
    assert metas[f"{OPF_META_PREFIX}title_sort"] == "& B <Teste>, A"  # artigo vai para o fim
    assert root.find(".//dc:publisher", NS).text == "Panini"
    ids = [n.attrib.get(f"{OPF}scheme") for n in root.findall(".//dc:identifier", NS)]
    assert ids.count(OPF_TRUSTED_SCHEME) == 1 and "ISBN" in ids
    assert root.find(".//dc:description", NS).text == "<p>Oi</p>"
