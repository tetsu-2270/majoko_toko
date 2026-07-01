def test_image_sorter_handles_rollover(sample_image_names):
    # TODO: ImageSorter実装後、IMG9999→IMG0001の順序を検証
    assert sample_image_names == ["IMG9998.jpg", "IMG9999.jpg", "IMG0001.jpg", "IMG0002.jpg"]
