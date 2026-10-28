# SPDX-License-Identifier: MIT
libdino_zink = shared_library(
  'dino_zink', 'dino_zink.c',
  include_directories : [inc_include, inc_src, inc_mesa, inc_gallium, inc_gallium_aux, inc_gallium_drivers],
  gnu_symbol_visibility : 'hidden',
  link_with : [libglapi, libgallium, libmesa],
  dependencies : [idep_mesautil, idep_xmlconfig, dep_thread, dep_clock, driver_zink,
                  dependency('appleframeworks', modules : ['IOSurface', 'Foundation'])],
  install : true,
)
