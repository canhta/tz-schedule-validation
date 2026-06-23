from verifier.server import parse_multipart

def test_parse_multipart_extracts_files_and_fields():
    boundary = b"----test"
    body = (
        b"------test\r\n"
        b'Content-Disposition: form-data; name="org"\r\n\r\n'
        b"Paper Moon\r\n"
        b"------test\r\n"
        b'Content-Disposition: form-data; name="raw"; filename="r.xlsx"\r\n'
        b"Content-Type: application/octet-stream\r\n\r\n"
        b"BINARYDATA\x00\x01\r\n"
        b"------test--\r\n"
    )
    fields = parse_multipart(body, boundary)
    assert fields["org"][1] == b"Paper Moon"
    assert fields["raw"][0] == "r.xlsx"
    assert fields["raw"][1] == b"BINARYDATA\x00\x01"
