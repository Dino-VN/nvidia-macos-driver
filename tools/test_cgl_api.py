#!/usr/bin/env python3
"""Public loader coverage must qualify both GL versions and extension strings."""
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'build'))
from opengl_api import requirements, supported
from generate_cgl_dispatch import collect_prototypes, SDK_HEADERS, signature, qualify_capabilities


class CGLAPITests(unittest.TestCase):
    def test_gl3_extensions_are_callable_prototypes_not_macros_or_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            headers = Path(directory)
            for name in SDK_HEADERS:
                (headers/name).write_text('')
            (headers/'gl3.h').write_text('GLAPI void APIENTRY glExisting(GLint value);\n')
            (headers/'gl3ext.h').write_text('''
#define GLAPI extern
#define HIDDEN \\
extern void glNotAnAPI(void);
/* extern void glCommentOnly(void); */
// extern void glLineComment(void);
GLAPI void APIENTRY glTexStorage2D(GLenum target, GLsizei levels, GLenum format, GLsizei width, GLsizei height);
extern void glTexStorage3D(GLenum target, GLsizei levels, GLenum format, GLsizei width, GLsizei height, GLsizei depth);
''')
            prototypes = collect_prototypes(headers)
            self.assertEqual(set(prototypes), {'glExisting','glTexStorage2D','glTexStorage3D'})
            self.assertEqual(prototypes['glTexStorage2D'][0], 'void')
            self.assertEqual(signature(prototypes['glTexStorage3D'][0],prototypes['glTexStorage3D'][2]),
                             'void:GLenum,GLsizei,GLenum,GLsizei,GLsizei,GLsizei')

    def contract(self):
        xml = '''<registry>
          <feature api="gl" number="1.0"><require><command name="glBegin"/><command name="glDraw"/></require></feature>
          <feature api="gl" number="3.2"><require><command name="glSync"/></require><remove profile="core"><command name="glBegin"/></remove></feature>
          <feature api="gl" number="4.1"><require><command name="glShader"/></require></feature>
          <feature api="gl" number="4.2"><require><command name="glStorage"/></require></feature>
          <feature api="gles2" number="9.0"><require><command name="glESOnly"/></require></feature>
          <extensions>
            <extension name="GL_ENUM_ONLY" supported="gl|glcore"><require><enum name="GL_MODE"/></require></extension>
            <extension name="GL_STORAGE" supported="gl|glcore"><require><command name="glStorage"/></require></extension>
            <extension name="GL_ALIASED" supported="gl|glcore"><require><command name="glDrawARB"/></require></extension>
            <extension name="GL_ES_ONLY" supported="gles2"><require><command name="glESOnly"/></require></extension>
            <extension name="GL_SPLIT" supported="gl|glcore|gles2"><require api="gl"><command name="glShader"/></require><require api="gles2"><command name="glESOnly"/></require></extension>
            <extension name="GL_LEGACY" supported="gl"><require><command name="glBegin"/></require></extension>
          </extensions></registry>'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'gl.xml';path.write_text(xml)
            return requirements(path)

    def test_core_removal_does_not_remove_compatibility_requirement(self):
        contract = self.contract()
        self.assertEqual(supported(contract, ['glDraw','glSync','glShader'], 'core')[0], 41)
        self.assertEqual(supported(contract, ['glDraw','glSync','glShader'], 'compatibility')[0], 0)
        self.assertEqual(supported(contract, ['glBegin','glDraw','glSync'], 'compatibility')[0], 32)

    def test_extensions_require_callable_symbols_including_aliases(self):
        contract = self.contract()
        version, extensions = supported(contract, ['glDraw','glSync','glShader'], 'core')
        self.assertEqual(version, 41)
        self.assertEqual(extensions, ['GL_ENUM_ONLY','GL_SPLIT'])
        version, extensions = supported(contract, ['glDraw','glSync','glShader','glStorage','glDrawARB'], 'core')
        self.assertEqual(version, 42)
        self.assertIn('GL_STORAGE', extensions)
        self.assertIn('GL_ALIASED', extensions)

    def test_desktop_contract_excludes_es_and_respects_profiles(self):
        contract = self.contract()
        self.assertNotIn('GL_ES_ONLY', contract['extensions']['core'])
        self.assertNotIn('GL_LEGACY', contract['extensions']['core'])
        self.assertEqual(contract['extensions']['core']['GL_SPLIT'], ['glShader'])
        self.assertIn('GL_LEGACY', supported(contract, ['glBegin'], 'compatibility')[1])


class CGLInheritedAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        xml = '''<registry>
          <feature api="gl" number="1.1"><require><command name="glVersion11"/></require></feature>
          <feature api="gl" number="3.0"><require><command name="glVersion30"/></require></feature>
          <feature api="gl" number="3.2"><require><command name="glVersion32"/></require></feature>
          <feature api="gl" number="3.3"><require><command name="glVersion33"/></require></feature>
          <feature api="gl" number="4.1"><require><command name="glVersion41"/></require></feature>
          <feature api="gl" number="4.5"><require><command name="glVersion45"/></require></feature>
          <extensions>
            <extension name="GL_ENUM_ONLY" supported="gl|glcore"><require><enum name="GL_MODE"/></require></extension>
            <extension name="GL_ARB_direct_state_access" supported="gl|glcore"><require><command name="glDSAARB"/></require></extension>
            <extension name="GL_EXT_direct_state_access" supported="gl|glcore"><require><command name="glDSAEXT"/></require></extension>
            <extension name="GL_ARB_texture_storage" supported="gl|glcore"><require>
              <command name="glTexStorage1D"/><command name="glTexStorage2D"/><command name="glTexStorage3D"/>
            </require></extension>
            <extension name="GL_OVR_multiview" supported="gl|glcore">
              <require><command name="glFramebufferTextureMultiviewOVR"/></require>
              <require feature="GL_VERSION_4_5"><command name="glNamedFramebufferTextureMultiviewOVR"/></require>
            </extension>
            <extension name="GL_ARB_gl_spirv" supported="gl|glcore"><require><command name="glSpecializeShaderARB"/></require></extension>
            <extension name="GL_ARB_sparse_texture" supported="gl|glcore">
              <require><command name="glTexPageCommitmentARB"/></require>
              <require extension="GL_EXT_direct_state_access"><command name="glTexturePageCommitmentEXT"/></require>
            </extension>
            <extension name="GL_OVR_multiview2" supported="gl|glcore"><require><enum name="GL_MODE"/></require></extension>
            <extension name="GL_ARB_spirv_extensions" supported="gl|glcore"><require><enum name="GL_MODE"/></require></extension>
            <extension name="GL_ARB_sparse_texture2" supported="gl|glcore"><require><enum name="GL_MODE"/></require></extension>
            <extension name="GL_ARB_sparse_texture_clamp" supported="gl|glcore"><require><enum name="GL_MODE"/></require></extension>
          </extensions>
        </registry>'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'gl.xml'
            path.write_text(xml)
            cls.contract = requirements(path)
        cls.descendants = {'GL_OVR_multiview2', 'GL_ARB_spirv_extensions',
                           'GL_ARB_sparse_texture2', 'GL_ARB_sparse_texture_clamp'}
        cls.storage = {'glTexStorage1D', 'glTexStorage2D', 'glTexStorage3D'}
        cls.sparse = {'GL_ARB_sparse_texture2', 'GL_ARB_sparse_texture_clamp'}

    def commands(self, version=41):
        return {f'glVersion{level}' for level in (11, 30, 32, 33, 41, 45) if level <= version}

    def extensions(self, *extra, version=41, profile='core'):
        return qualify_capabilities(self.contract, self.commands(version) | set(extra), profile)[1]

    def test_commandless_descendants_do_not_survive_missing_inherited_apis(self):
        storage = {'glTexStorage1D', 'glTexStorage2D', 'glTexStorage3D'}
        for profile in ('core', 'compatibility'):
            with self.subTest(profile=profile):
                commands = self.commands() | storage
                old_version, old_extensions = supported(self.contract, commands, profile)
                version, extensions = qualify_capabilities(self.contract, commands, profile)
                self.assertEqual(version, old_version)
                self.assertEqual(set(old_extensions) - set(extensions), self.descendants)
                self.assertEqual(extensions, ['GL_ARB_texture_storage', 'GL_ENUM_ONLY'])

    def test_multiview_requires_bound_attachment_but_not_conditional_named_dsa(self):
        extensions = self.extensions('glFramebufferTextureMultiviewOVR')
        self.assertIn('GL_OVR_multiview2', extensions)
        # The generic own-command list includes the conditional named DSA call.
        # Its parent's string must not become an unconditional dependency.
        self.assertNotIn('GL_OVR_multiview', extensions)
        self.assertNotIn('GL_OVR_multiview2', self.extensions('glNamedFramebufferTextureMultiviewOVR'))

    def test_spirv_accepts_callable_specialization_alias_without_full_gl46(self):
        for alias in ('glSpecializeShaderARB', 'glSpecializeShader'):
            with self.subTest(alias=alias):
                extensions = self.extensions('glShaderBinary', alias)
                self.assertIn('GL_ARB_spirv_extensions', extensions)
                if alias == 'glSpecializeShader':
                    self.assertNotIn('GL_ARB_gl_spirv', extensions)

    def test_spirv_requires_both_binary_loading_and_specialization(self):
        for extra in ((), ('glShaderBinary',), ('glSpecializeShader',), ('glSpecializeShaderARB',)):
            with self.subTest(extra=extra):
                self.assertNotIn('GL_ARB_spirv_extensions', self.extensions(*extra))

    def test_spirv_preserves_inherited_gl33_requirement_even_with_callable_alias(self):
        for profile in ('core', 'compatibility'):
            with self.subTest(profile=profile):
                self.assertNotIn('GL_ARB_spirv_extensions', self.extensions(
                    'glShaderBinary', 'glSpecializeShader', version=32, profile=profile))
                self.assertIn('GL_ARB_spirv_extensions', self.extensions(
                    'glShaderBinary', 'glSpecializeShader', version=33, profile=profile))

    def test_sparse_descendants_require_bound_commitment_not_named_dsa(self):
        for name in self.sparse:
            with self.subTest(extension=name):
                self.assertNotIn(name, self.extensions(*self.storage))
                self.assertNotIn(name, self.extensions(*self.storage, 'glTexturePageCommitmentEXT'))
                self.assertNotIn(name, self.extensions(*self.storage, 'glTexturePageCommitmentARB'))
                self.assertIn(name, self.extensions(*self.storage, 'glTexPageCommitmentARB'))
        self.assertNotIn('GL_ARB_sparse_texture', self.extensions(*self.storage, 'glTexPageCommitmentARB'))

    def test_sparse_descendants_require_all_immutable_allocation_apis(self):
        for name in self.sparse:
            for missing in self.storage:
                with self.subTest(extension=name, missing=missing):
                    commands = (self.storage - {missing}) | {'glTexPageCommitmentARB'}
                    self.assertNotIn(name, self.extensions(*commands))
            self.assertNotIn(name, self.extensions('glTexPageCommitmentARB'))

    def test_multiview_and_sparse_preserve_inherited_minimum_versions(self):
        self.assertNotIn('GL_OVR_multiview2', self.extensions('glFramebufferTextureMultiviewOVR', version=11))
        self.assertIn('GL_OVR_multiview2', self.extensions('glFramebufferTextureMultiviewOVR', version=30))
        for name in self.sparse:
            with self.subTest(extension=name):
                self.assertNotIn(name, self.extensions(*self.storage, 'glTexPageCommitmentARB', version=0))
                self.assertIn(name, self.extensions(*self.storage, 'glTexPageCommitmentARB', version=11))

    def test_exposed_dsa_extensions_require_the_conditional_named_apis(self):
        bound = self.storage | {'glFramebufferTextureMultiviewOVR', 'glTexPageCommitmentARB'}
        for marker, dsa_name in (('glDSAARB', 'GL_ARB_direct_state_access'),
                                 ('glDSAEXT', 'GL_EXT_direct_state_access')):
            for profile in ('core', 'compatibility'):
                with self.subTest(dsa=dsa_name, profile=profile):
                    extensions = self.extensions(*bound, marker, profile=profile)
                    self.assertIn(dsa_name, extensions)
                    self.assertNotIn('GL_OVR_multiview2', extensions)
                    self.assertTrue(self.sparse.isdisjoint(extensions))
                    extensions = self.extensions(*bound, marker, 'glNamedFramebufferTextureMultiviewOVR',
                                                 'glTexturePageCommitmentEXT', profile=profile)
                    self.assertIn('GL_OVR_multiview2', extensions)
                    self.assertTrue(self.sparse.issubset(extensions))
                    # A named ARB spelling is not the specified sparse DSA API.
                    extensions = self.extensions(*bound, marker, 'glTexturePageCommitmentARB', profile=profile)
                    self.assertTrue(self.sparse.isdisjoint(extensions))

    def test_gl45_requires_named_dsa_apis_without_an_extension_string(self):
        bound = self.storage | {'glFramebufferTextureMultiviewOVR', 'glTexPageCommitmentARB'}
        for profile in ('core', 'compatibility'):
            with self.subTest(profile=profile):
                extensions = self.extensions(*bound, version=45, profile=profile)
                self.assertNotIn('GL_ARB_direct_state_access', extensions)
                self.assertNotIn('GL_EXT_direct_state_access', extensions)
                self.assertNotIn('GL_OVR_multiview2', extensions)
                self.assertTrue(self.sparse.isdisjoint(extensions))
                extensions = self.extensions(*bound, 'glNamedFramebufferTextureMultiviewOVR',
                                             'glTexturePageCommitmentEXT', version=45, profile=profile)
                self.assertIn('GL_OVR_multiview2', extensions)
                self.assertTrue(self.sparse.issubset(extensions))

    def test_independent_enum_only_and_callable_texture_storage_remain_eligible(self):
        extensions = self.extensions('glTexStorage1D', 'glTexStorage2D', 'glTexStorage3D')
        self.assertIn('GL_ENUM_ONLY', extensions)
        self.assertIn('GL_ARB_texture_storage', extensions)
        self.assertNotIn('GL_ARB_texture_storage', self.extensions('glTexStorage2D', 'glTexStorage3D'))


if __name__ == '__main__':
    unittest.main()
