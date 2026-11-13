"""Known answers for options-all-recommended.py. Run: python3 test_options_all_recommended.py"""

import importlib.util
import os

spec = importlib.util.spec_from_file_location(
    "oar", os.path.join(os.path.dirname(__file__), "options-all-recommended.py"))
oar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oar)

# i) the failure this exists for: one recommended, one not
two = """## App > X
**Next steps for us (options)**
1. ADD: build the thing (Recommended, removes the skips)
2. ENHANCE: tighten the specs, about 15 min
"""
assert oar.unrecommended(two) == ["2. ENHANCE: tighten the specs, about 15 min"]

# ii) every option recommended, and a numbered list elsewhere is ignored
ok = """Steps:
1. not an option
### Next steps for us (options)
1. `/flush all` (Recommended, low risk)
2. DECIDE: A or B /options (Recommended: A, cheaper)
### Waiting on
1. not an option either
"""
assert oar.unrecommended(ok) == []

# iii) no options section at all
assert oar.unrecommended("## App > X\n\nDone. Nothing outstanding.\n") == []

# iv) a crossroad: bare DECIDE line, numbered roads, exactly one tagged
cross = """### Next steps for us (options)
DECIDE: what the tag becomes /options
1. Role tag 'potential client' (Recommended): no clash
2. No tag, use closeness stage
3. Rename the pool
"""
assert oar.unrecommended(cross) == []

# v) a crossroad with two roads tagged, or none, blocks
assert len(oar.unrecommended(cross.replace("2. No tag, use closeness stage", "2. No tag (Recommended)"))) == 2
assert len(oar.unrecommended(cross.replace(" (Recommended)", ""))) == 3

print("ok")
