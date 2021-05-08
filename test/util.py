import time
import requests
from requests.exceptions import ConnectionError
from PIL import Image, ImageChops

from layman.util import url_for as layman_url_for


def url_for(endpoint, *, internal=True, **values):
    return layman_url_for(endpoint, internal=internal, **values)


def url_for_external(endpoint, **values):
    assert not values.get('internal', False)
    return url_for(endpoint, internal=False, **values)


# utils
def wait_for_url(url, max_attempts, sleeping_time):
    attempt = 1
    while True:
        # print(f"Waiting for URL {url}, attempt {attempt}")
        try:
            # Just checking the url, no need to store result
            requests.get(url)
            break
        except ConnectionError as e:
            if attempt == max_attempts:
                print(f"Max attempts reached")
                raise e
            attempt += 1
        time.sleep(sleeping_time)


def compare_images(image1, image2):
    expected_image = Image.open(image1)
    current_image = Image.open(image2)

    diff_image = ImageChops.difference(expected_image, current_image)

    diffs = 0

    for x in range(diff_image.width):
        for y in range(diff_image.height):
            pixel_diff = diff_image.getpixel((x, y))
            if pixel_diff != (0, 0, 0, 0) and \
                    (expected_image.getpixel((x, y))[3] > 0 or current_image.getpixel((x, y))[3] > 0):
                diffs += 1

    return diffs
