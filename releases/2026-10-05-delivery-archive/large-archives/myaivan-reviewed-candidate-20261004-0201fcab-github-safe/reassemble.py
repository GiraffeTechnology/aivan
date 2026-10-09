import hashlib
import json
import pathlib
import zipfile

root = pathlib.Path(__file__).resolve().parent
manifest = json.loads((root / "manifest.json").read_text())
output = root / manifest["reassembled_filename"]
if output.exists():
    raise SystemExit("Output already exists; move it aside before reconstructing.")
temporary = output.with_name(output.name + ".assembling")
if temporary.exists():
    raise SystemExit("An incomplete output exists; inspect or remove it before retrying.")
digest = hashlib.sha256()
total = 0
try:
    with temporary.open("xb") as target:
        for part in manifest["parts"]:
            wrapper = root / part["filename"]
            payload = wrapper.read_bytes()
            if len(payload) != part["size"] or hashlib.sha256(payload).hexdigest() != part["sha256"]:
                raise ValueError("Wrapper integrity mismatch: " + part["filename"])
            with zipfile.ZipFile(wrapper) as archive:
                if archive.namelist() != [part["member"]]:
                    raise ValueError("Unexpected ZIP members: " + part["filename"])
                chunk = archive.read(part["member"])
            if len(chunk) != part["chunk_size"] or hashlib.sha256(chunk).hexdigest() != part["chunk_sha256"]:
                raise ValueError("Segment integrity mismatch: " + part["filename"])
            target.write(chunk)
            digest.update(chunk)
            total += len(chunk)
    if total != manifest["reassembled_size"] or digest.hexdigest() != manifest["reassembled_sha256"]:
        raise ValueError("Reassembled archive integrity mismatch")
    temporary.rename(output)
    print("Verified: " + output.name)
except BaseException:
    if temporary.exists():
        temporary.unlink()
    raise
