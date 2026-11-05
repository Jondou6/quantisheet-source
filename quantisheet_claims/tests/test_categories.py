"""T15 and findings 19, 21."""
import hashlib

from quantisheet_claims import categories

# sha256[:16] of each of the 86 codes in the pasted categories.ts. Only
# hashes are kept, so the vendor-style list itself is not shipped.
PASTED_CODE_HASHES = ('2dde6d03ddaa287e', 'ee71241ebf18aa7e', 'b7179fe74411d2b7', 'e237563d9503bb38', '0d4618da86543944', '362d88818ef27ef2', '13539f4ba1f154cc', '047aaa859de4a39a', 'a3dbc4b644a9a2c5', 'f0c5fdda4d5fe35b', '6e587f8a282ae34f', 'd3acacd34e0ddd85', '78088af3164cdc6a', '2c929313580667c4', '030055fa790be3c4', '5eca1a91a6b4f1d7', '25f90501f6db3c52', '91feb80e6b283267', 'ef6a49df162c77e5', '97d4f7ac4c1d01fa', '4ea451c7ea75bbd4', 'fafd789f4bfb160a', '80e7645d07c8a58f', '49e86f0286aa4484', 'eabd110ebd63de7b', '9e917138f198c5b7', '23d28eb032ab1470', 'f7b3730232dcb5cb', 'febfe9b049de62b3', '94b67525e6065393', '1bed464d640e57db', '33204bd617145e14', '7609d821ea4b8609', '85869174459f3b9c', '7bb8698b6399f6b9', 'f435321e192ee99b', '27f22ac999744a1b', '376215ae291376ec', 'fac7ae9ae7caf527', '87ff5eaa9f41d71e', '2e04f6bb390c4082', '7a62e3ac3d7c06e2', '8853564f13080823', 'e3c6b9ac4ccae3f0', '6ad4182884b6f065', 'f48719e0f19f019e', 'af73a498b248a551', 'eadd339142795599', '20437d6916e507d8', 'bb1ab6e46f180bf4', 'f4726ecd396f63e2', '70acd28f254172ff', 'eafc6b05785b9972', '7213e90f5a3ff611', '46996aa935f7cee7', '86d78d6566218054', 'df004f89b82e934f', 'f754105b74d860b3', 'd50b424fce6df960', '2dd44638d2dae1f3', '17fbef925503c981', 'd537c888e1c0667c', 'c5d9a635e6929b68', '1f5998b5f01949b9', '9254682f9a4f7d34', '40f29adb67622dce', '5505bbe316987e07', 'e1bad657cc0ddd36', '4725e5eca9e1c5c5', 'f7bd60bb5186bf16', '1dc23bf32db811b4', 'a2ce8cde9b222e75', '99322d4d10cf5332', 'e789e660565bca11', '15f54bb6f2cda05e', '29598948b369b71c', 'f141c21e56228cb3', '5e35f6236dc4e34e', '16e2374a68967c36', '52bdaca2b5afdf8e', 'd1a4f781e49036d7', 'b3456a379f89141a', '63d6db973f2feae6', '122f898f93094f45', '033fe6f4aa3a10f7', 'f7b4388a3cb7b967')


def test_t15_every_category_has_one_group_and_label():
    cats = categories.categories()
    assert len(cats) == 17          # + Sales tax (NW-15)
    for code, (label, group) in cats.items():
        assert label.strip() and group.strip(), code
    assert categories.group_for("WATER") == "Mitigation"      # finding 19


def test_t15_no_pasted_code_is_shipped():
    assert len(PASTED_CODE_HASHES) == 86
    ours = {hashlib.sha256(c.encode()).hexdigest()[:16]
            for c in categories.categories()}
    assert ours & set(PASTED_CODE_HASHES) == set()            # finding 21


def test_settings_can_add_category(claims_home):
    from quantisheet_claims import settings
    settings.set("categories", {"mold": ["Mold remediation", "Mitigation"]})
    settings.reload()
    assert categories.label("MOLD") == "Mold remediation"
    assert categories.group_for("MOLD") == "Mitigation"
