from copy import deepcopy
import io
import hashlib
import struct
import tempfile
from unittest.mock import patch
from pathlib import Path
import sys
import unittest

from PIL import Image,PngImagePlugin

sys.path.insert(0,str(Path(__file__).resolve().parent))
import asa_content_identity as c
from asa_eligibility import legal_rows


def png(color=(1,2,3),size=(3,2),*,level=0,text=None,mode='RGB'):
    image=Image.new(mode,size,color);stream=io.BytesIO();info=PngImagePlugin.PngInfo()
    if text is not None:info.add_text('comment',text)
    image.save(stream,format='PNG',compress_level=level,pnginfo=info)
    return stream.getvalue()


def roles():
    return {r:{k:set() for k in c.ANCHOR_TYPES} for r in c.ROLES}


def fp(name,raw=None):
    return {'image':name,**c.png_fingerprint(png() if raw is None else raw)}


class ContentIdentityTests(unittest.TestCase):
    def graph(self,pairs=None,rows=None,protected=None,metadata=None,byte_unknown=(),pixel_unknown=()):
        return c.build_asa_content_inventory(
            [('11111111','a.png')] if pairs is None else pairs,
            [fp('a.png')] if rows is None else rows,roles() if protected is None else protected,
            metadata_images=['a.png'] if metadata is None else metadata,
            unknown_byte_images=byte_unknown,unknown_pixel_images=pixel_unknown)

    def test_different_png_bytes_same_pixels_join_development_and_validation(self):
        a=fp('a.png',png(level=0));b=fp('b.png',png(level=9,text='different encoding'))
        self.assertNotEqual(a['bytes_sha256'],b['bytes_sha256'])
        self.assertEqual(a['rgb_sha256'],b['rgb_sha256'])
        protected=roles();protected['core']['codes']={'11111111'}
        protected['validation']['codes']={'22222222'}
        private,aggregate=self.graph([('11111111','a.png'),('22222222','b.png')],
                                    [a,b],protected,['a.png','b.png'])
        self.assertEqual(private['node_groups']['c:11111111'],private['node_groups']['c:22222222'])
        self.assertEqual(aggregate['observed_protected_intersections']['core__validation'],1)
        self.assertTrue(aggregate['supplied_pixel_closure_complete'])
        # Complete evidence reports the bridge; it does NOT authorize using it.
        self.assertFalse(aggregate['external_source_completeness_proven'])

    def test_dimensions_are_bound_even_when_flat_rgb_byte_sequence_matches(self):
        a=c.png_fingerprint(png(size=(1,6)));b=c.png_fingerprint(png(size=(2,3)))
        self.assertNotEqual(a['rgb_sha256'],b['rgb_sha256'])

    def test_missing_inventory_only_image_prevents_global_byte_and_pixel_claim(self):
        private,aggregate=self.graph(metadata=['a.png','orphan.png'],
                                     byte_unknown=['orphan.png'],pixel_unknown=['orphan.png'])
        self.assertIn('i:orphan.png',private['node_groups'])
        self.assertFalse(aggregate['supplied_byte_closure_complete'])
        self.assertFalse(aggregate['supplied_pixel_closure_complete'])
        self.assertEqual(aggregate['unknown_byte_image_count'],1)

    def test_byte_complete_without_pixel_evidence_cannot_claim_content_closure(self):
        row=fp('a.png')
        row.update(rgb_sha256=None,width=None,height=None,algorithm=None)
        _,aggregate=self.graph(rows=[row],pixel_unknown=['a.png'])
        self.assertTrue(aggregate['supplied_byte_closure_complete'])
        self.assertFalse(aggregate['supplied_pixel_closure_complete'])

    def test_unassociated_zip_image_is_included_and_matches_historical_pixel_anchor(self):
        extra=fp('orphan.png',png((9,8,7)));protected=roles()
        protected['history']['rgb_hashes']={extra['rgb_sha256']}
        private,aggregate=self.graph(rows=[fp('a.png'),extra],protected=protected)
        self.assertEqual(aggregate['supplied_image_universe'],2)
        self.assertEqual(private['protected_groups']['history'],
                         {private['node_groups']['i:orphan.png']})

    def test_unknown_inventories_and_associated_metadata_coverage_are_exact(self):
        for change,error in [({'metadata':[]},'associated_metadata'),
                             ({'byte_unknown':['ghost.png']},'unknown_byte'),
                             ({'pixel_unknown':['ghost.png']},'unknown_pixel')]:
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,error):
                self.graph(**change)
        for name in ('bad\n.png','bad\0.png','bad\x7f.png'):
            with self.subTest(name=repr(name)),self.assertRaisesRegex(ValueError,'control_character'):
                self.graph(metadata=['a.png',name],byte_unknown=[name],pixel_unknown=[name])

    def test_basename_byte_and_pixel_conflicts_cannot_disappear_by_overwrite(self):
        first=fp('a.png');different=fp('a.png',png((9,8,7)))
        with self.assertRaisesRegex(ValueError,'basename_bytes'):
            self.graph(rows=[first,different])
        bad=deepcopy(first);bad['rgb_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'conflicting_pixels'):
            self.graph(rows=[first,bad])
        private,_=self.graph(rows=[first,deepcopy(first)])
        self.assertEqual(private['fingerprints']['a.png'],first)

    def test_same_pixel_digest_cannot_have_different_dimensions_or_algorithm(self):
        first=fp('a.png');bad=fp('b.png',png((9,8,7)))
        bad['rgb_sha256']=first['rgb_sha256'];bad['width']+=1
        with self.assertRaisesRegex(ValueError,'pixel_dimensions'):
            self.graph(rows=[first,bad])
        for field,value in [('algorithm','png-rgb-u32be-v1'),('algorithm','png-model-input-rgb-u32be-v2'),('algorithm','unknown-v0'),('width',True),('height',float('nan'))]:
            bad=deepcopy(first);bad[field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'pixel_semantics'):
                self.graph(rows=[bad])

    def test_unmatched_pixel_anchor_blocks_pixel_claim_only(self):
        protected=roles();protected['validation']['rgb_hashes']={'f'*64}
        _,aggregate=self.graph(protected=protected)
        self.assertTrue(aggregate['supplied_byte_closure_complete'])
        self.assertFalse(aggregate['supplied_pixel_closure_complete'])
        self.assertEqual(aggregate['unmatched_protected_anchor_counts']['validation'],1)
        del protected['validation']['rgb_hashes']
        with self.assertRaisesRegex(ValueError,'anchor_types'):
            self.graph(protected=protected)

    def test_same_pixels_with_conflicting_gram_references_are_not_four_legal_portions(self):
        images=[fp('a.png',png((1,2,3))),fp('b.png',png((4,5,6))),
                fp('c.png',png((7,8,9))),fp('d.png',png((1,2,3),level=9,text='copy'))]
        private,_=self.graph([('11111111',row['image']) for row in images],images,
                             metadata=[row['image'] for row in images])
        metadata=[{'FoodCode':'11111111','Image':row['image'],'ImageType':'PORTION',
                   'ModCode':0,'PortionCode':98,'Multiplier':10*(i+1)}
                  for i,row in enumerate(images)]
        inventory=[{'FileName':row['image'],'Portion':f'portion {i}'}
                   for i,row in enumerate(images)]
        arguments=dict(permitted_codes=['11111111'],fndds_codes=['11111111'],top_codes=['11111111'])
        byte_only,_=legal_rows(metadata,inventory,[],image_hashes={row['image']:row['bytes_sha256']
                              for row in images},**arguments)
        pixel_aware,_=legal_rows(metadata,inventory,[],image_hashes={name:row['rgb_sha256']
                                for name,row in private['fingerprints'].items()},**arguments)
        self.assertEqual(len(byte_only['rows']),4)
        self.assertEqual(pixel_aware['rows'],[])
        self.assertEqual(pixel_aware['ambiguous_code_images'],
                         {('11111111','a.png'),('11111111','d.png')})

    def test_unsupported_rendering_and_corrupt_images_refuse_instead_of_becoming_unknown(self):
        for raw in [b'not an image',png()[:-12]]:
            with self.subTest(length=len(raw)),self.assertRaises(ValueError):
                c.png_fingerprint(raw)
        image=Image.new('RGB',(2,2));stream=io.BytesIO();image.save(stream,format='JPEG')
        with self.assertRaisesRegex(ValueError,'bounded_png'):
            c.png_fingerprint(stream.getvalue())
        with self.assertRaisesRegex(ValueError,'bounded_png_bytes'):
            c.png_fingerprint(b'x'*(c.MAX_BYTES+1))

    def test_model_encoder_equivalence_for_alpha_profile_orientation_and_palette(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src'))
        from opt_pipeline import encode_image
        def save(image, **options):
            stream=io.BytesIO();image.save(stream,format='PNG',**options)
            return stream.getvalue()
        rgb=Image.new('RGB',(3,2),(1,2,3))
        rgba=rgb.convert('RGBA');rgba.putalpha(0)
        rgba_other=rgba.copy();rgba_other.putalpha(182)
        la=Image.new('LA',(3,2),(7,0));la_other=Image.new('LA',(3,2),(7,182))
        palette=Image.new('P',(3,2));palette.putpalette([1,2,3]+[0]*765)
        exif=Image.Exif();exif[274]=6
        pairs=[(save(rgba),save(rgba_other)),
               (save(la),save(la_other)),
               (save(rgb),save(rgb,icc_profile=b'synthetic ignored profile')),
               (save(rgb),save(rgb,exif=exif)),
               (save(palette,transparency=0),save(rgb))]
        with tempfile.TemporaryDirectory() as directory:
            for index,(a,b) in enumerate(pairs):
                with self.subTest(index=index):
                    fa,fb=c.png_fingerprint(a),c.png_fingerprint(b)
                    self.assertNotEqual(fa['bytes_sha256'],fb['bytes_sha256'])
                    self.assertEqual(fa['rgb_sha256'],fb['rgb_sha256'])
                    paths=[Path(directory)/f'{index}-{j}.png' for j in range(2)]
                    for path,body in zip(paths,(a,b)):path.write_bytes(body)
                    for mode in ('native','square256'):
                        self.assertEqual(encode_image(paths[0],mode),encode_image(paths[1],mode))
                    with Image.open(io.BytesIO(a)) as image:
                        expected=hashlib.sha256(c.ALGORITHM.encode()+b'\0'
                            +struct.pack('>II',3,2)+image.convert('RGB').tobytes()).hexdigest()
                    self.assertEqual(fa['rgb_sha256'],expected)

    def test_jpeg_and_png_decoded_model_input_identity_matches_actual_encoder(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src'))
        from opt_pipeline import encode_image
        image=Image.new('RGB',(7,5));image.putdata([(i*7%256,i*13%256,i*19%256) for i in range(35)])
        out=io.BytesIO();image.save(out,format='JPEG');jpeg=out.getvalue()
        with Image.open(io.BytesIO(jpeg)) as decoded:
            out=io.BytesIO();decoded.convert('RGB').save(out,format='PNG');png_raw=out.getvalue()
        a,b=(c.image_fingerprint(raw) for raw in (jpeg,png_raw))
        self.assertNotEqual(a['bytes_sha256'],b['bytes_sha256'])
        self.assertEqual(a['rgb_sha256'],b['rgb_sha256'])
        self.assertEqual(a['algorithm'],'image-model-input-rgb-u32be-v3')
        with tempfile.TemporaryDirectory() as temp:
            paths=[Path(temp)/'jpeg-disguised.png',Path(temp)/'decoded.png']
            for path,raw in zip(paths,(jpeg,png_raw)):path.write_bytes(raw)
            for mode in ('native','square256'):
                self.assertEqual(encode_image(paths[0],mode),encode_image(paths[1],mode))
        with self.assertRaisesRegex(ValueError,'bounded_png'):
            c.png_fingerprint(jpeg)
        for truncated in (jpeg[:len(jpeg)//2],jpeg[:-2]):
            with self.subTest(length=len(truncated)),self.assertRaises(ValueError):
                c.image_fingerprint(truncated)
        out=io.BytesIO();image.save(out,format='GIF')
        with self.assertRaisesRegex(ValueError,'bounded_image'):
            c.image_fingerprint(out.getvalue())

    def test_animation_crc_bounds_and_pixel_permutation_refuse_or_differ(self):
        image=Image.new('RGB',(2,2));stream=io.BytesIO()
        image.save(stream,format='PNG',save_all=True,
                   append_images=[Image.new('RGB',(2,2),(1,2,3))])
        for decoder in (c.png_fingerprint,c.image_fingerprint):
            with self.assertRaisesRegex(ValueError,'animated_'):
                decoder(stream.getvalue())
        corrupt=bytearray(png());corrupt[29]^=1  # IHDR CRC, not image pixels
        with self.assertRaises(ValueError):c.png_fingerprint(bytes(corrupt))
        with patch.object(c,'MAX_PIXELS',1),self.assertRaisesRegex(ValueError,'bounded_png'):
            c.png_fingerprint(png())
        a=Image.new('RGB',(2,1));a.putdata([(1,2,3),(4,5,6)])
        b=Image.new('RGB',(2,1));b.putdata([(4,5,6),(1,2,3)])
        raws=[]
        for image in (a,b):
            out=io.BytesIO();image.save(out,format='PNG');raws.append(out.getvalue())
        self.assertNotEqual(*(c.png_fingerprint(raw)['rgb_sha256'] for raw in raws))

    def test_returns_are_detached_from_inputs_and_aggregate_contains_no_identifiers(self):
        row=fp('a.png');protected=roles();protected['core']['images']={'a.png'}
        private,aggregate=self.graph(rows=[row],protected=protected)
        row['width']=99;protected['core']['images'].clear()
        self.assertEqual(private['fingerprints']['a.png']['width'],3)
        self.assertEqual(len(private['protected_groups']['core']),1)
        self.assertNotIn('a.png',str(aggregate));self.assertNotIn('11111111',str(aggregate))


if __name__=='__main__':unittest.main()
