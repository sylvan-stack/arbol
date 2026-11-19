"""Record and verify the selected Arbol release in private recovery storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from archive_volume import Archive, ArchiveUnavailable, require_archive
else:
    _archive = import_module(".archive_volume", __package__) if __package__ else import_module("archive_volume")
    Archive, ArchiveUnavailable, require_archive = _archive.Archive, _archive.ArchiveUnavailable, _archive.require_archive

COMMIT = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
LABEL = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*")
MUTABLE_BUILD_FILES = {"build.log", "last-start", ".use.lock"}
SEALED_LAYOUT_2 = {"arbol", "arbol-claude-driver", "arbol-codex-driver", "arbol-mimo-driver"}


class RecoveryError(ValueError):
    """A recovery gate could not be established."""


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def document(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_bytes())
    if not isinstance(data, dict):
        raise RecoveryError("Expected a JSON object.")
    return data


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_private(path: Path, value: object) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def private_dir(path: Path) -> Path:
    path = path.resolve(strict=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RecoveryError("Recovery storage must be in a directory accessible only to its owner.")
    return path


def recovery_dir(path: Path, archive: Archive | None) -> Path:
    """Keep local inputs private and validate Mercury by volume and path."""
    if archive is None:
        return private_dir(path)
    checked = archive.backup_path(path)
    if not checked.is_dir():
        raise RecoveryError("A recovery directory is required on Mercury.")
    return checked


@contextmanager
def publish_directory(destination: Path, *, archive: Archive | None = None) -> Iterator[Path]:
    parent = recovery_dir(destination.parent, archive)
    destination = parent / destination.name
    if archive is not None:
        archive.backup_path(destination, allow_missing=True)
    if os.path.lexists(destination):
        raise RecoveryError("The recovery output already exists.")
    with tempfile.TemporaryDirectory(prefix=".recovery-", dir=parent) as temporary:
        staging = Path(temporary) / "output"
        staging.mkdir(mode=0o700)
        yield staging
        if archive is not None:
            archive.backup_path(staging)
            archive.backup_path(destination, allow_missing=True)
        if os.path.lexists(destination):
            raise RecoveryError("The recovery output already exists.")
        staging.rename(destination)


def relative(value: str) -> Path:
    path = Path(value)
    if not path.parts or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise RecoveryError("An evidence path is not a safe relative path.")
    return path


def tree(folder: Path, *, exclude: frozenset[str] = frozenset()) -> dict[str, object]:
    """Bind file bytes, executable bits and contained symlinks without following directory links."""
    result: dict[str, object] = {}
    for path in sorted(folder.rglob("*")):
        name = path.relative_to(folder).as_posix()
        if name in exclude:
            continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            link = os.readlink(path)
            if Path(link).is_absolute() or not path.resolve(strict=True).is_relative_to(folder):
                raise RecoveryError("A selected payload has a symlink outside its saved directory.")
            result[name] = {"link": link}
        elif stat.S_ISREG(info.st_mode):
            result[name] = {"sha256": digest(path), "executable": info.st_mode & 0o111}
        elif not stat.S_ISDIR(info.st_mode):
            raise RecoveryError("A selected payload contains a special file.")
    return result


def git(checkout: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(checkout), *args], capture_output=True, timeout=60, check=False,
        env={"HOME": str(Path.home()), "PATH": "/usr/bin:/bin", "GIT_NO_REPLACE_OBJECTS": "1"},
    )
    if result.returncode:
        raise RecoveryError("A recorded Git revision or input is unavailable.")
    return result.stdout


def commit_id(value: object) -> str:
    if not isinstance(value, str) or not COMMIT.fullmatch(value):
        raise RecoveryError("The selected source needs a full Git commit ID.")
    return value


def source_file(checkout: Path, commit: str, prefix: str, name: str) -> bytes:
    return git(checkout, "show", f"{commit}:{prefix}{relative(name).as_posix()}")


def repository_root(checkout: Path) -> Path:
    root = Path(os.fsdecode(git(checkout, "rev-parse", "--show-toplevel").rstrip(b"\n")))
    return root.resolve(strict=True)


def save_sources(checkout: Path, commit: str, destination: Path) -> None:
    # git archive writes directly to the private staging directory.
    git(repository_root(checkout), "archive", "--format=tar", f"--output={destination}", commit)


def retain_source(
    checkout: Path, commit: str, output: Path, *, native_consumer_parent: str | None = None,
) -> dict[str, str]:
    repository = repository_root(checkout)
    source_tree = commit_id(git(repository, "rev-parse", f"{commit}^{{tree}}").decode().strip())
    archive = output / "source.tar"
    retained = output / "source.git"
    git(repository, "archive", "--format=tar", f"--output={archive}", commit)
    git(output, "init", "--bare", "--initial-branch=recovery", "--template=", str(retained))
    # A transport fetch writes independent objects and preserves the original
    # commit. The shallow boundary excludes earlier revisions from the record.
    refs = [f"{commit}:refs/heads/recovery"]
    if native_consumer_parent is not None:
        refs.append(f"{native_consumer_parent}:refs/heads/native-consumer-parent")
    git(retained, "-c", "protocol.file.allow=always", "fetch", "--no-tags", "--no-write-fetch-head",
        "--depth=1", "--no-recurse-submodules", repository.as_uri(), *refs)
    git(retained, "fsck", "--full", "--no-reflogs")
    retained_commit, retained_tree = git(retained, "rev-parse", "HEAD", "HEAD^{tree}").decode().splitlines()
    if (retained_commit != commit or retained_tree != source_tree
            or os.path.lexists(retained / "objects/info/alternates")):
        raise RecoveryError("The retained Git repository differs from the selected source.")
    if native_consumer_parent is not None:
        retained_parent = git(retained, "rev-parse", "refs/heads/native-consumer-parent").decode().strip()
        if retained_parent != native_consumer_parent:
            raise RecoveryError("The retained Git repository lacks the Browser Native predecessor.")
    with tempfile.NamedTemporaryFile(prefix=".source-", dir=output) as comparison:
        git(retained, "archive", "--format=tar", f"--output={comparison.name}", commit)
        archive_digest = digest(archive)
        if digest(Path(comparison.name)) != archive_digest:
            raise RecoveryError("The retained Git sources differ from the selected source archive.")
    return {"tree": source_tree, "repository": retained.name, "archive": archive.name, "archiveSha256": archive_digest}


def check_hashes(folder: Path, hashes: object) -> None:
    if not isinstance(hashes, dict) or not hashes:
        raise RecoveryError("The package does not record its file hashes.")
    for name, expected in hashes.items():
        path = folder / relative(name)
        if not path.resolve(strict=True).is_relative_to(folder) or digest(path) != expected:
            raise RecoveryError(f"Package evidence differs for {name}.")


def renderer_evidence(
    folder: Path, build: str, checkout: Path, commit: str, design_checkout: Path, *, external: bool,
) -> dict[str, object]:
    renderer = document(folder / "bundle.json")
    if renderer.get("format") != 1 or renderer.get("build") != build:
        raise RecoveryError("The renderer does not belong to the selected Build.")
    if external and renderer.get("sourceCommit") != commit:
        raise RecoveryError("The App renderer differs from its committed source reference.")
    check_hashes(folder, renderer.get("files"))
    if renderer["lockSha256"] != sha(source_file(checkout, commit, "ui/elma/", "package-lock.json")):
        raise RecoveryError("The renderer lock does not match its Git revision.")
    sources = renderer["sources"]
    if not isinstance(sources, dict) or not sources:
        raise RecoveryError("The renderer does not record its source hashes.")
    for name, expected in sources.items():
        if sha(source_file(checkout, commit, "ui/elma/", name)) != expected:
            raise RecoveryError(f"Renderer source evidence differs for {name}.")
    design = renderer["designSystem"]
    design_source = source_file(checkout, commit, "ui/elma/", "design-system/manifest.json")
    if design["manifestSha256"] != sha(design_source) or json.loads(design_source)["commit"] != design["commit"]:
        raise RecoveryError("The renderer design reference does not match its source.")
    design_commit = commit_id(design["commit"])
    git(design_checkout, "cat-file", "-e", design_commit + "^{commit}")
    return {"sourceCommit": commit, "designCommit": design_commit, "lockSha256": renderer["lockSha256"]}


def python_evidence(
    manifest: dict[str, Any], checkout: Path, commit: str, prefix: str, folder: Path,
) -> dict[str, object]:
    python = manifest["python"]
    pin = json.loads(source_file(checkout, commit, prefix, "scripts/python-distribution.json"))
    distribution = pin["distributions"][python["target"]]
    if python["version"] != pin["version"] or python["archiveSha256"] != distribution["sha256"]:
        raise RecoveryError("The packaged interpreter differs from the committed toolchain pin.")
    for field, expected in (("provider", pin["provider"]), ("release", pin["release"]),
                            ("archiveUrl", distribution["url"])):
        if field in python and python[field] != expected:
            raise RecoveryError("The packaged interpreter provenance differs from its pin.")
    path = folder / relative(python["executable"])
    if not path.resolve(strict=True).is_relative_to(folder):
        raise RecoveryError("The package interpreter is outside the selected payload.")
    if digest(path) != python.get("executableSha256", python.get("sha256")):
        raise RecoveryError("The packaged interpreter does not match its digest.")
    lock = source_file(checkout, commit, prefix, "uv.lock")
    packages = {entry["name"]: entry["version"] for entry in tomllib.loads(lock.decode())["package"]}
    dependencies = manifest.get("dependencies", {})
    if any(packages.get(name) != version for name, version in dependencies.items()):
        raise RecoveryError("A packaged dependency differs from its lock.")
    for name in ("package.json", "pyproject.toml", ".python-version", "uv.lock", "arbol-build.json",
                 "scripts/python-distribution.json"):
        path = folder / name
        if not path.is_file():
            continue
        original = source_file(checkout, commit, prefix, name)
        if name == "package.json" and manifest["component"] == "arbol":
            expected = json.loads(original)
            for key in ("schemaCompatibility", "installationLayout"):
                if key in manifest:
                    expected[key] = manifest[key]
            if document(path) == expected:
                continue
        if path.read_bytes() != original:
            raise RecoveryError(f"Packaged input differs from its Git revision: {name}.")
    return {"python": python, "uvVersion": pin["uvVersion"], "lockSha256": sha(lock), "dependencies": dependencies}


def retain_signed_app(app: Path, destination: Path) -> str:
    """Save the exact signed native bundle and verify that the copied payload still validates."""
    if app.suffix != ".app" or not stat.S_ISDIR(app.lstat().st_mode):
        raise RecoveryError("The App entry must be inside a native bundle.")
    before = tree(app)
    for bundle in (app, destination):
        if bundle == destination:
            subprocess.run(
                ["/usr/bin/ditto", "--rsrc", "--extattr", "--acl", str(app), str(destination)],
                capture_output=True, check=True, timeout=120,
            )
        verified = subprocess.run(
            ["/usr/bin/codesign", "--verify", "--strict", str(bundle)], capture_output=True, check=False, timeout=60,
        )
        if verified.returncode:
            raise RecoveryError("The selected App or retained copy did not verify against its code signature.")
    if tree(destination) != before:
        raise RecoveryError("The retained App differs from the exact signed bundle.")
    return sha(canonical(before))


def sealed_payload_evidence(payload: Path, component: str, build: str, commit: str, git_tree: str) -> dict[str, str]:
    application = Path(__file__).resolve().parents[1]
    source = application / "driver-payload/src"
    if not source.is_dir():
        source = application / "src"
    sys.path.insert(0, str(source))
    try:
        verifier = import_module("arbol_builds.driver_payload")
        verified = verifier.load(payload, component, build)
    except (ImportError, OSError, ValueError) as error:
        raise RecoveryError("The selected immutable package could not be verified.") from error
    finally:
        sys.path.pop(0)
    descriptor = verified.descriptor
    if descriptor["source"] != {"commit": commit, "tree": git_tree}:
        raise RecoveryError("The immutable package differs from its committed Git tree.")
    return {"descriptorSha256": str(verified.digest), "manifestSha256": str(descriptor["payloadManifestSha256"])}


def retain_pinned_input(source: Path, destination: Path, expected: str, *, executable: bool = False) -> None:
    if (not DIGEST.fullmatch(expected) or source.is_symlink() or not source.is_file()
            or (executable and not os.access(source, os.X_OK)) or digest(source) != expected):
        raise RecoveryError(f"The exact recovery input is unavailable: {destination.name}.")
    shutil.copyfile(source, destination)
    destination.chmod(0o700 if executable else 0o600)
    if digest(destination) != expected:
        raise RecoveryError(f"A pinned input changed while copying: {destination.name}.")


def driver_metadata_evidence(
    folder: Path, record: dict[str, Any], checkout: Path, commit: str, prefix: str, *, git_tree: str | None,
) -> dict[str, Any]:
    path = folder / "package-metadata.json"
    metadata = document(path)
    pin = json.loads(source_file(checkout, commit, prefix, "scripts/python-distribution.json"))
    distribution = pin["distributions"][metadata["target"]]
    if (metadata.get("component") != record["component"] or metadata.get("version") != record["packageVersion"]
            or metadata.get("sourceCommit") != commit or metadata.get("uncommittedChanges") is not False
            or (git_tree is not None and metadata.get("sourceTree") != git_tree)
            or metadata.get("python") != pin["version"] or metadata.get("distribution") != pin["release"]
            or metadata.get("archiveSha256") != distribution["sha256"]):
        raise RecoveryError("The Driver package metadata differs from the selected Build or its committed Python pin.")
    files = metadata["files"]
    interpreter = "runtime/python/bin/python3.14"
    check_hashes(folder, files)
    if interpreter not in files or not os.access(folder / interpreter, os.X_OK):
        raise RecoveryError("The Driver package does not verify its interpreter.")
    return {"packageMetadataSha256": digest(path), "uvVersion": pin["uvVersion"],
            "python": {"version": pin["version"], "target": metadata["target"], "provider": pin["provider"],
                       "release": pin["release"], "archiveUrl": distribution["url"],
                       "archiveSha256": distribution["sha256"], "executableSha256": files[interpreter]}}


def browser_files(folder: Path) -> dict[str, str]:
    return {name: sha(b"symlink\0" + os.fsencode(value["link"])) if "link" in value else value["sha256"]
            for name, value in tree(folder).items() if isinstance(value, dict)}


def browser_literal(source: str, name: str) -> str:
    match = re.search(rf"^(?:export )?const {re.escape(name)} = '([^'\n]+)';$", source, re.MULTILINE)
    if match is None:
        raise RecoveryError(f"The committed Browser recipe does not identify {name}.")
    return match[1]


def browser_admission(
    audit: dict[str, Any], recipe: str, checkout: Path, commit: str, output: Path,
) -> dict[str, Any]:
    review = commit_id(audit["reviewHandover"])
    forester = Path(browser_literal(recipe, "foresterRoot"))
    handover = browser_literal(recipe, "handoverPath")
    origin = git(forester, "remote", "get-url", "origin").decode().strip()
    if origin not in {"git@github.com:sylvan-stack/forester-artifacts.git",
                      "https://github.com/sylvan-stack/forester-artifacts.git"}:
        raise RecoveryError("The Browser review is outside its published authority.")
    git(forester, "merge-base", "--is-ancestor", review, "refs/remotes/origin/main")
    text = source_file(forester, review, "", handover).decode()
    blocks = re.findall(r"<!-- ABR-29-HOST-SOURCE-ADMISSION:BEGIN -->\s*([\s\S]*?)\s*"
                        r"<!-- ABR-29-HOST-SOURCE-ADMISSION:END -->", text)
    if len(blocks) != 1:
        raise RecoveryError("The published Browser admission is missing or ambiguous.")
    admission = json.loads(blocks[0])
    fields = ("productDigest", "productSources", "productOutputs", "compilerInputs")
    if admission.get("status") != "accepted" or any(admission.get(key) != audit[key] for key in fields):
        raise RecoveryError("The signed Browser does not match its published admission.")
    admitted_commit = commit_id(admission["sourceGit"])
    git(checkout, "merge-base", "--is-ancestor", admitted_commit, commit)
    # The Browser signer uses Node's English collation recursively. Invoke only
    # this pure JSON canonicalizer to compare its signed digest across languages.
    algorithm = ("let input=''; for await (const chunk of process.stdin) input+=chunk;"
                 "const canon=JSON.stringify(JSON.parse(input),(_k,x)=>x&&typeof x==='object'&&!Array.isArray(x)"
                 "?Object.fromEntries(Object.entries(x).sort(([a],[b])=>a.localeCompare(b,'en'))):x);"
                 "process.stdout.write(canon)")
    node = shutil.which("node")
    if node is None:
        raise RecoveryError("The Browser recovery toolchain requires Node.")
    canonical_review = subprocess.run(
        [node, "--input-type=module", "--eval", algorithm], check=True, capture_output=True, timeout=30,
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        input=canonical({"foresterCommit": review, "handoverPath": handover, "admission": admission}),
    ).stdout
    if sha(canonical_review) != audit["reviewDigest"]:
        raise RecoveryError("The published Browser admission differs from the signed policy digest.")
    write_private(output / "browser-admission.json", admission)
    checkpoint, verdict = admission["sourceCheckpoint"], admission["sourceVerdict"]
    retain_pinned_input(Path(checkpoint["path"]), output / "browser-source-checkpoint.json", checkpoint["sha256"])
    retain_pinned_input(Path(verdict["path"]), output / "browser-source-verdict.md", verdict["sha256"])
    checked = document(output / "browser-source-checkpoint.json")
    if (checked.get("source") != admitted_commit or checked.get("ordinal") != admission["acceptedSourceOrdinal"]
            or any(admission[key] != checked.get(key) for key in fields)
            or not re.search(r"^Accepted\.?\s*$", (output / "browser-source-verdict.md").read_text(), re.I | re.M)
            or checkpoint["sha256"] not in (output / "browser-source-verdict.md").read_text()):
        raise RecoveryError("The retained Browser source verdict and checkpoint do not match.")
    return {"foresterCommit": review, "origin": origin, "handoverPath": handover,
            "sourceCommit": admitted_commit, "reviewDigest": audit["reviewDigest"]}


def retain_browser_consumer(platform: str, compiler: dict[str, Any], output: Path) -> dict[str, str]:
    manifest = Path(browser_literal(platform, "frozenConsumer"))
    expected = browser_literal(platform, "frozenDigest")
    original = manifest.parent.resolve(strict=True)
    retained = output / "browser-native-inputs"
    retained.mkdir(mode=0o700)

    def retain(path: Path, checksum: str) -> Path:
        if path.resolve(strict=True) != path:
            raise RecoveryError("A Browser qualification input is not physical.")
        target = retained / path.relative_to(original)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        retain_pinned_input(path, target, checksum)
        return target

    consumer = document(retain(manifest, expected))
    if consumer.get("pageAdmission") is not False:
        raise RecoveryError("Browser native qualification requires its isolated consumer.")
    header_root = Path(browser_literal(platform, "officialHeaders"))
    for name, checksum in compiler["native"]["headerHashes"].items():
        retain(header_root / relative(name), checksum)
    review = consumer["sourceReviewManifest"]
    frozen = document(retain(Path(review["path"]), review["sha256"]))
    record = frozen["sourceRecord"]
    if record != consumer["sourceRecord"]:
        raise RecoveryError("The Browser native source records disagree.")
    sources = document(retain(Path(record["path"]), record["sha256"]))
    for root, files in ((Path(frozen["frozenSource"]), sources["sources"]),
                        (Path(frozen["frozenDist"]), frozen["compiledInventory"])):
        for name, checksum in files.items():
            retain(root / relative(name), checksum)
    inventory = consumer["bundle"]["inventory"]
    inventory_doc = document(retain(Path(inventory["path"]), inventory["sha256"]))
    candidate = Path(consumer["candidate"])
    copied = retained / candidate.relative_to(original)
    retain_signed_app(candidate, copied)
    compatibility = consumer["manifest"]
    compatibility_path = copied / Path(compatibility["path"]).relative_to(candidate)
    if browser_files(copied) != inventory_doc["files"] or digest(compatibility_path) != compatibility["sha256"]:
        raise RecoveryError("The retained Browser Native fixture differs from the pinned input.")
    return {"originalDirectory": str(original), "path": retained.name, "manifestSha256": expected,
            "sourceParent": commit_id(consumer["parent"])}


def browser_package_evidence(
    folder: Path, record: dict[str, Any], checkout: Path, commit: str, prefix: str, output: Path,
) -> dict[str, Any]:
    app = folder / "app/ArbolBrowser.app"
    if app.resolve(strict=True) != app or not app.is_dir():
        raise RecoveryError("The working Browser needs its physical signed host.")
    publisher = json.loads(source_file(checkout, commit, prefix, "native/publisher-requirement.json"))
    identifier = publisher["bundleIdentifier"]
    if not LABEL.fullmatch(identifier):
        raise RecoveryError("The Browser publisher identifier is invalid.")
    subprocess.run(["/usr/bin/codesign", "--verify", "--strict", "--deep", "-R",
                    f'={publisher["requirement"]} and identifier "{identifier}"', str(app)],
                   check=True, capture_output=True, timeout=60)
    resources = app / "Contents/Resources"
    policy_path = resources / "host-policy.json"
    metadata_path = resources / "browser/metadata.json"
    compat_path = resources / "native-compatibility.json"
    policy, metadata, compat = map(document, (policy_path, metadata_path, compat_path))
    inner_entry = (resources / "browser/bin/arbol-browser").read_bytes()
    original_operand = b'"$(/usr/bin/dirname -- "$0")/.."'
    mounted_operand = b'"$(/usr/bin/dirname -- "$0")/../app/ArbolBrowser.app/Contents/Resources/browser"'
    if (inner_entry.count(original_operand) != 1
            or inner_entry.replace(original_operand, mounted_operand) != (folder / record["entry"]).read_bytes()):
        raise RecoveryError("The Browser Build entry differs from its signed host entry.")
    audits = list(folder.glob(".host-preparation-*.app.signature-audit.json"))
    if len(audits) != 1 or not stat.S_ISREG(audits[0].lstat().st_mode):
        raise RecoveryError("The signed Browser Build has no unique signature audit.")
    audit = document(audits[0])
    identity = {"repositoryDigest": sha(os.fsencode(record["source"]["repository"])),
                "commit": commit, "branch": record["source"]["branch"], "uncommittedChanges": False}
    signed_digests = {"policyDigest": digest(policy_path), "metadataDigest": digest(metadata_path),
                      "compatibilityDigest": digest(compat_path)}
    expected_component = {"name": record["component"], "version": record["packageVersion"],
                          "build": record["build"], "contract": record["contract"],
                          "profileFormat": record["dataFormat"]}
    if (policy.get("format") != 1 or policy.get("build") != record["build"] or policy.get("buildRoot") != str(folder)
            or policy.get("metadataDigest") != signed_digests["metadataDigest"]
            or policy.get("compatibilityDigest") != signed_digests["compatibilityDigest"]
            or metadata.get("component") != expected_component or metadata.get("sourceIdentity") != identity
            or audit.get("sourceIdentity") != identity or audit.get("publisher") != publisher
            or any(audit.get(key) != value for key, value in signed_digests.items())
            or any(audit.get(key) != policy.get(key) for key in ("sourceDigest", "productDigest", "reviewDigest"))
            or audit.get("sourceDigest") != metadata.get("sourceDigest")
            or any(audit.get(key) != metadata["host"].get(key) for key in ("productDigest", "compileDigest"))
            or document(resources / "publisher-requirement.json") != publisher
            or compat.get("publisherTeam") != publisher["team"] or compat.get("bundleIdentifier") != identifier
            or audit.get("files") != browser_files(app)):
        raise RecoveryError("The Browser signature audit, publisher, signed policy or source does not match the Build.")
    recipe = source_file(checkout, commit, prefix, "scripts/package-host.mjs").decode()
    review = browser_admission(audit, recipe, checkout, commit, output)
    for name, expected in audit["productSources"].items():
        data = source_file(checkout, commit, prefix, name)
        if name == "arbol-build.json":
            config = json.loads(data)
            del config["checks"]
            data = json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode()
        if sha(data) != expected:
            raise RecoveryError(f"The admitted Browser product differs from the selected source: {name}.")
    platform = source_file(checkout, commit, prefix, "scripts/compile-platform.mjs").decode()
    compiler = audit["compilerInputs"]
    native_input = retain_browser_consumer(platform, compiler, output)
    stock = Path(browser_literal(recipe, "preservedStockArchive"))
    stock_pin = re.search(r"export const stockElectronArchive = Object\.freeze\(\{ name: '[^']+',\s*"
                          r"sha256: '([0-9a-f]{64})' \}\);", recipe)
    if stock_pin is None:
        raise RecoveryError("The exact Browser Electron archive pin is unavailable.")
    retain_pinned_input(stock, output / stock.name, stock_pin[1])
    write_private(output / "browser-signature-audit.json", audit)
    return {"review": review, "nativeInput": native_input, "publisher": publisher, "policySha256": signed_digests["policyDigest"],
            "compileSha256": audit["compileDigest"], "compilerInputs": compiler,
            "stockElectron": {"originalPath": str(stock), "path": stock.name, "sha256": stock_pin[1]}}


def capture_build(
    item: dict[str, Any], output: Path, index: int, inventory: dict[str, Any],
) -> dict[str, Any]:
    folder = Path(item["directory"]).resolve(strict=True)
    record = document(folder / "build.json")
    component = record["component"]
    build = record["build"]
    if (record.get("status") != "working" or record.get("prunedAt") is not None
            or not re.fullmatch(r"[1-9a-z][0-9a-z]*", build)):
        raise RecoveryError("Select a working, numbered Build.")
    source = record["source"]
    if source.get("uncommittedChanges") is not False:
        raise RecoveryError("The Build record does not establish clean source; its exact Git inputs are unresolved.")
    checkout = Path(item.get("checkout") or source["repository"]).resolve(strict=True)
    commit = commit_id(source["commit"])
    prefix = git(checkout, "rev-parse", "--show-prefix").decode().strip()
    entry = relative(record["entry"])
    build_config = json.loads(source_file(checkout, commit, prefix, "arbol-build.json"))
    version = json.loads(source_file(checkout, commit, prefix, "package.json"))["version"]
    layout = record.get("installationLayout", 1)
    source_layout = build_config.get("installationLayout", 1)
    entry_path = folder / entry
    if (build_config["component"] != component or build_config["entry"] != record["entry"]
            or type(layout) is not int or layout < 1 or type(source_layout) is not int or source_layout != layout
            or build_config.get("schemaCompatibility") != record.get("schemaCompatibility")
            or version != record["packageVersion"] or not entry_path.resolve(strict=True).is_relative_to(folder)
            or not entry_path.is_file() or not os.access(entry_path, os.X_OK)):
        raise RecoveryError("Build identity, entry or package version differs from its committed configuration.")
    expected_checks = [{"name": check["name"], "passed": True} for check in build_config["checks"]]
    recorded_checks = record.get("checks")
    if recorded_checks != expected_checks or any(check["passed"] is not True for check in recorded_checks):
        raise RecoveryError("The Build has not recorded every committed check as successful.")

    evidence: dict[str, Any] = {}
    payload = folder
    sealed = folder / "driver-payload"
    git_tree = None
    native_consumer_parent = None
    if os.path.lexists(sealed) or (layout >= 2 and component in SEALED_LAYOUT_2):
        git_tree = commit_id(git(checkout, "rev-parse", f"{commit}^{{tree}}").decode().strip())
        evidence["sealedPayload"] = sealed_payload_evidence(sealed, component, build, commit, git_tree)
        if component != "arbol":
            payload = sealed
    manifest_file = payload / "package-manifest.json"
    if manifest_file.is_file():
        manifest = document(manifest_file)
        # Sealed Driver manifests predate the installation layout declaration.
        # Their exact Build/source identity was verified above and the layout is
        # bound by the committed description and registry record.
        packaged_layout = manifest.get("installationLayout", layout if payload == sealed else 1)
        if (manifest.get("format") != 1 or manifest.get("candidate", False) is not False
                or type(packaged_layout) is not int or packaged_layout != layout
                or any(manifest.get(key) != record.get(key)
                       for key in ("component", "build", "entry", "packageVersion", "root", "schemaCompatibility"))
                or manifest["source"].get("commit") != commit
                or manifest["source"].get("uncommittedChanges") is not False
                or manifest["source"].get("componentPath", prefix.rstrip("/")) != prefix.rstrip("/")):
            raise RecoveryError("The package manifest differs from the selected Build or its source.")
        check_hashes(payload, manifest["files"])
        evidence["packageManifestSha256"] = digest(manifest_file)
        if "python" in manifest:
            evidence.update(python_evidence(manifest, checkout, commit, prefix, payload))
        if component == "arbol" and inventory["kind"] == "legacy":
            # Packaging read this from another checkout; the Arbol commit cannot identify those bytes.
            contract_layout = folder / "tests/backend/layout.sql"
            expected = manifest["contractLayoutSha256"]
            if not DIGEST.fullmatch(expected) or digest(contract_layout) != expected:
                raise RecoveryError("The exact packaged Root Contract SQL is unresolved.")
            shutil.copy2(contract_layout, output / "root-contract.sql")
            evidence["rootContract"] = {"sha256": expected, "path": "root-contract.sql"}
        if component == "arbol" and "renderer" in manifest:
            renderer = manifest["renderer"]
            bundled = folder / relative(renderer["path"])
            if digest(bundled / "bundle.json") != renderer["bundleSha256"]:
                raise RecoveryError("The packaged renderer manifest differs from the backend package.")
            evidence["renderer"] = renderer_evidence(
                bundled, build, checkout, commit, Path(inventory["designCheckout"]), external=False,
            )
            design = evidence["renderer"]["designCommit"]
            save_sources(Path(inventory["designCheckout"]), design, output / "design-source.tar")
    elif component == "arbol-app":
        # The native App embeds a separate renderer receipt instead of package-manifest.json.
        app = folder / entry.parts[0]
        renderer_commit = commit_id(source_file(checkout, commit, prefix, "renderer-source.txt").decode().strip())
        renderer_checkout = Path(inventory["rendererCheckout"])
        design_checkout = Path(inventory["designCheckout"])
        evidence["renderer"] = renderer_evidence(
            app / "Contents/Resources/ui/elma", build, renderer_checkout, renderer_commit,
            design_checkout, external=True,
        )
        save_sources(renderer_checkout, renderer_commit, output / "renderer-source.tar")
        save_sources(design_checkout, evidence["renderer"]["designCommit"], output / "design-source.tar")
        evidence["nativeToolchain"] = "Preserved signed executable; exact compiler version not emitted by this packager."
    elif component in {"arbol-pi-driver", "arbol-mimo-driver"} and (payload / "package-metadata.json").is_file():
        evidence.update(driver_metadata_evidence(payload, record, checkout, commit, prefix, git_tree=git_tree))
        if component == "arbol-mimo-driver" and layout >= 2:
            native_source = source_file(checkout, commit, prefix, "src/arbol_mimo_driver/native_version.py").decode()
            native_pin = re.search(r'^NATIVE_SHA256 = "([0-9a-f]{64})"$', native_source, re.MULTILINE)
            if native_pin is None or not isinstance(item.get("nativeCandidate"), str):
                raise RecoveryError("The exact Mimo native qualification candidate is required.")
            name = "mimo-native-candidate"
            retain_pinned_input(Path(item["nativeCandidate"]), output / name, native_pin[1], executable=True)
            evidence["nativeCandidate"] = {"path": name, "sha256": native_pin[1]}
    elif component == "arbol-browser":
        browser = browser_package_evidence(folder, record, checkout, commit, prefix, output)
        evidence["browser"] = browser
        native_consumer_parent = browser["nativeInput"]["sourceParent"]
    elif not component.endswith("-driver") or layout != 1:
        raise RecoveryError("The Build has no verifiable package manifest.")

    if component == "arbol-app":
        package = output / "package"
        package.mkdir(mode=0o700)
        app_name = entry.parts[0]
        bundle_sha256 = retain_signed_app(folder / app_name, package / app_name)
        write_private(package / "build.json", record)
        evidence["signedApp"] = {"path": f"package/{app_name}", "filesSha256": bundle_sha256}
    else:
        before = tree(folder, exclude=frozenset(MUTABLE_BUILD_FILES))
        evidence["installedFilesSha256"] = sha(canonical(before))
    evidence["gitSource"] = retain_source(checkout, commit, output, native_consumer_parent=native_consumer_parent)
    return {"component": component, "build": build, "root": record.get("root"), "entry": str(entry),
            "packageVersion": version, "installationLayout": layout, "sourceCommit": commit,
            "componentPath": prefix.rstrip("/"),
            "buildConfigurationSha256": sha(source_file(checkout, commit, prefix, "arbol-build.json")),
            "evidence": evidence, "savedAt": f"builds/{index}"}


def copy_configuration(files: dict[str, str], destination: Path) -> list[str]:
    destination.mkdir(mode=0o700)
    for name, source in sorted(files.items()):
        if not LABEL.fullmatch(name):
            raise RecoveryError("Configuration and dependency labels must be simple names.")
        path = Path(source)
        if path.is_symlink() or not path.is_file():
            raise RecoveryError(f"Required configuration or file dependency is unavailable: {name}.")
        target = destination / name
        before = digest(path)
        shutil.copyfile(path, target)
        target.chmod(0o600)
        if digest(target) != before:
            raise RecoveryError(f"A recovery input changed while copying: {name}.")
    return sorted(files)


def record_release(inventory_path: Path, destination: Path) -> str:
    archive = require_archive()
    private_dir(inventory_path.parent)
    inventory = document(inventory_path)
    kind = inventory["kind"]
    if kind not in ("legacy", "current") or not isinstance(inventory["builds"], list):
        raise RecoveryError("Select a legacy or current release with an explicit Build inventory.")
    configuration = inventory["configuration"]
    required = {"installation", "root"} if kind == "legacy" else {"installation"}
    if not isinstance(configuration, dict) or not required <= configuration.keys():
        raise RecoveryError("Installation and applicable legacy settings must be saved.")
    with publish_directory(destination, archive=archive) as output:
        builds = []
        problems = []
        for index, item in enumerate(inventory["builds"]):
            build_output = output / "builds" / str(index)
            build_output.mkdir(parents=True, mode=0o700)
            try:
                builds.append(capture_build(item, build_output, index, inventory))
            except RecoveryError as error:
                problems.append(f"Build inventory entry {index + 1}: {error}")
            except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
                problems.append(f"Build inventory entry {index + 1}: required source or package evidence is unreadable.")
        components = {build["component"] for build in builds}
        if "arbol" not in components or (kind == "legacy" and "arbol-root" not in components):
            problems.append("Select Arbol and, for a legacy release, its Root Build.")
        keys = {(build["component"], build["build"]) for build in builds}
        if len(keys) != len(builds):
            problems.append("A selected Build appears more than once.")
        if kind == "legacy" and not any(build["evidence"].get("rootContract") for build in builds):
            problems.append("The legacy Arbol package must preserve its exact external Root Contract SQL.")
        if problems:
            raise RecoveryError("Unresolved release provenance: " + " ".join(problems))
        labels = copy_configuration(configuration, output / "configuration")
        inputs = copy_configuration(inventory.get("inputs", {}), output / "inputs")
        payload = {"format": 1, "kind": kind, "builds": builds, "configuration": labels, "inputs": inputs,
                   "files": tree(output)}
        receipt = output / "release.json"
        write_private(receipt, payload)
        return digest(receipt)


def verify_release(folder: Path, expected: str | None = None, *,
                   archive: Archive | None = None) -> tuple[dict[str, Any], str]:
    folder = recovery_dir(folder, archive)
    path = folder / "release.json"
    if not stat.S_ISREG(path.lstat().st_mode):
        raise RecoveryError("The release record must be a private regular file.")
    data = path.read_bytes()
    actual = sha(data)
    if expected is not None and actual != expected:
        raise RecoveryError("The release record does not match the snapshot.")
    value = json.loads(data)
    if (not isinstance(value, dict) or value.get("format") != 1 or value.get("kind") not in ("legacy", "current")
            or not value.get("builds") or not value.get("configuration")
            or value.get("files") != tree(folder, exclude=frozenset({"release.json"}))):
        raise RecoveryError("Required release payloads or recovery configuration differ from the release record.")
    return value, actual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = record_release(args.inventory, args.output)
    except ArchiveUnavailable as error:
        print(json.dumps({"status": error.code, "message": str(error)}), file=sys.stderr)
        return 1
    except RecoveryError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
        print("Cannot record release: an inventory or required file could not be read or saved.", file=sys.stderr)
        return 1
    print(json.dumps({"releaseSha256": result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
