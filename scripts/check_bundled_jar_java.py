"""Build-time guard: fail if a bundled Java jar needs a newer JRE than is installed.

owlready2 bundles Pellet plus a set of Jena jars to read RDF/XML. From owlready2
0.50 onward those Jena jars are recompiled for Java 25 (class file version 69),
which crashes Pellet with UnsupportedClassVersionError on the Java 21 runtime in
this image. That regression slipped in silently when the owlready2 pin was open.

This script makes the failure loud at build time instead of at a user's first
RDF/XML upload: it compares the highest class file version inside the bundled
Jena jars against what the installed JRE supports, and exits non-zero on a
mismatch so `docker build` fails.

Run during the image build (see Dockerfile). Exit 0 = OK, exit 1 = mismatch.
"""
import glob
import os
import re
import struct
import subprocess
import sys
import zipfile

# A Java class file's major version is the JDK feature version + 44
# (Java 8 -> 52, Java 17 -> 61, Java 21 -> 65, Java 25 -> 69).
CLASS_VERSION_OFFSET = 44


def jre_max_class_version():
    """Highest class file version the installed `java` can load."""
    out = subprocess.run(["java", "-version"], capture_output=True, text=True).stderr
    m = re.search(r'version "([0-9._]+)"', out or "")
    if not m:
        raise SystemExit("could not determine Java version from `java -version`")
    ver = m.group(1)
    # "1.8.0_xxx" -> feature 8; "21.0.11" -> feature 21.
    feature = int(ver.split(".")[1]) if ver.startswith("1.") else int(ver.split(".")[0])
    return feature + CLASS_VERSION_OFFSET, feature


def worst_bundled_jena_class():
    """(max_major, jar_name) across all .class entries in the bundled Jena jars."""
    import owlready2
    pellet_dir = os.path.join(os.path.dirname(owlready2.__file__), "pellet")
    worst, worst_jar = 0, None
    jars = glob.glob(os.path.join(pellet_dir, "*jena*.jar"))
    if not jars:
        raise SystemExit(f"no Jena jars found in {pellet_dir}")
    for jar in jars:
        with zipfile.ZipFile(jar) as z:
            for name in z.namelist():
                if not name.endswith(".class"):
                    continue
                header = z.read(name)[:8]
                if len(header) >= 8:
                    major = struct.unpack(">H", header[6:8])[0]
                    if major > worst:
                        worst, worst_jar = major, os.path.basename(jar)
    return worst, worst_jar


def main():
    jre_max, jre_feature = jre_max_class_version()
    worst, worst_jar = worst_bundled_jena_class()
    if worst > jre_max:
        sys.stderr.write(
            f"\nFATAL: bundled Jena jar {worst_jar} contains classes compiled for "
            f"Java {worst - CLASS_VERSION_OFFSET} (class file {worst}), but the image's "
            f"JRE only supports up to Java {jre_feature} (class file {jre_max}).\n"
            f"Pellet would die with UnsupportedClassVersionError on RDF/XML input.\n"
            f"Fix: pin owlready2 to a version with older Jena jars, or install a newer JRE.\n"
        )
        sys.exit(1)
    print(f"jar/JRE check OK: worst Jena class file = {worst} ({worst_jar}); "
          f"JRE supports up to {jre_max} (Java {jre_feature}).")


if __name__ == "__main__":
    main()
