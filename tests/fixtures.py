"""Sample shaders, project files and a network-free mcmeta client, shared by several modules."""

from ggraft.sources import Blob, McMeta

# The last #include sits inside a conditional, as it does in terrain.vsh.
NESTED = """#version 330
#extension GL_ARB_separate_shader_objects : require

#include <minecraft:fog.glsl>
#include <minecraft:terrainglobals.glsl>
#ifndef MULTIDRAW_TERRAIN
    #include <minecraft:chunksection.glsl>
#endif

void main() {
    gl_Position = ProjMat * ModelViewMat * vec4(pos, 1.0);
}
"""

CONDITIONAL_INCLUDE = """#version 330
#ifdef X
#include <ns:x.glsl>
#endif
void main() {}
"""

CONFIG = """[base]
dir = "base"
[patches]
dir = "patches"
[output]
dir = "out"
header = false
"""

REPLACE_PATCH = """targets = [{targets}]
[[injection]]
op = "replace"
at = "gl_Position = {{x}};"
with = "gl_Position = iso({{x}});"
"""


class Offline(McMeta):
    """McMeta without the network: one file per tag, named after it."""

    def list_blobs(self, tag, source):
        return [Blob(f"core/{tag.split('-')[0].replace('.', '_')}.vsh", 4)]

    def _open(self, url):
        return b"#version 330\n"
