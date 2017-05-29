#!/usr/bin/env python

import re
import os
import io
import sys
import requests
import argparse
import json
from bs4 import BeautifulSoup
from libs import hls

VERSION = "1.1.3"

TVAPI_HEADERS  = {'app-version-android': '999'}
TVAPI_BASE_URL = "https://tvapi.nrk.no/v1/programs/{}"
MIMIR_BASE_URL = "https://mimir.nrk.no/plugin/1.0/static?mediaId={}"

def progress(pct):
    sys.stdout.write("\rProgress: {}%".format(pct))
    sys.stdout.flush()


def error(message):
    print("Error: {}".format(message))

    
def get_req(url, headers = None):
    try:
        req = requests.get(url, headers = headers)
    except requests.exceptions.MissingSchema:
        req = get_req("https://{}".format(url), session)
    except requests.exceptions.RequestException as e:
        error(e)
        req = None
    return req


def create_filename_base(title):
    basename = re.sub('[/\\\?%\*:|"<>]', '_', title)
    if os.path.isfile(u'{}.ts'.format(basename)):
        i = 1
        while os.path.isfile(u'{} ({}).ts'.format(basename, i)):
            i += 1
        basename = u'{} ({}).ts'.format(basename, i)
    return basename

    
def nrk_vtt_to_srt(vtt):
    vtt_cues = re.split('\r?\n\r?\n', vtt)[1:]  # First block is 'WEBVTT' and headers
    srt_cues = []
    for cue in vtt_cues:
        cue_lines = cue.splitlines()
        cue_lines[1] = cue_lines[1].replace('.', ',')
        srt_cues.append('\n'.join(cue_lines))
    return '\n\n'.join(srt_cues)


def get_vtt_file_url(media_url):
    main_manifest_req = get_req(media_url)
    for line in main_manifest_req.text.splitlines():
        if line.startswith('#EXT-X-MEDIA:TYPE=SUBTITLES'):
            sub_stream_line = line
            break
    sub_manifest_url = re.search('URI="([^"]+)"', sub_stream_line).group(1)
    sub_manifest_req = get_req(sub_manifest_url)
    for line in sub_manifest_req.text.splitlines():
        if not line[0] == '#':
            sub_filename = line
            break
    return requests.compat.urljoin(sub_manifest_url, sub_filename)


def save_subtitles(media_url, filename):
    print(u"Saving {}".format(filename))
    sub_url = get_vtt_file_url(media_url)
    vtt_req = get_req(sub_url)
    srt = nrk_vtt_to_srt(vtt_req.text)

    with io.open(filename, 'w') as f:
        f.write(srt)


def save_stream(json_data):
    title = json_data.get('fullTitle') or json_data.get('title')
    print(u"Found {}".format(title))
    filename_base = create_filename_base(title)

    if json_data.get('hasSubtitles'):
        save_subtitles(json_data['mediaUrl'], u'{}.srt'.format(filename_base))

    print(u"Saving {}.ts\n".format(filename_base))
    hls.dump(json_data['mediaUrl'], u'{}.ts'.format(filename_base), progress)


def download(program_id):
    req = get_req(TVAPI_BASE_URL.format(program_id), TVAPI_HEADERS)
    response_data = req.json()
    if not response_data:
        error("Empty response from server. Non-existing program ID?")
    elif 'mediaUrl' not in response_data:
        error("Could not find media stream. No longer available?")
    else:
        save_stream(response_data)
        print('\n')


def get_program_id_from_html(url):
    # Returns None if not found in html
    req = get_req(url)
    if not req:
        program_id = None
    else:
        soup = BeautifulSoup(req.text, 'lxml')
        id_element = soup.find('section', {'id': 'program-info'}) or soup.figure
        if not id_element:
            program_id = None
        else:
            program_id = (id_element.get('data-ga-from-id') or
                          id_element.get('data-video-id'))
    return program_id


def get_program_id_from_media_id(media_id):
    url = MIMIR_BASE_URL.format(media_id)
    req = get_req(url)
    if not req:
        program_id = None
    else:
        soup = BeautifulSoup(req.text, 'lxml')
        json_info = json.loads(soup.script.get_text())
        program_id = json_info.get('activeMedia', {}).get('psId')
    return program_id


def get_program_id(passed_string):
    # Extract program ID from string:
    program_id_match = (re.search("(^|/)([A-Z]{4}\d{8})($|/)", passed_string) or
                        re.search("(^|/)PS\*([\da-f-]+)($|/)", passed_string))
    if program_id_match:
        program_id = program_id_match.group(2)
    else:
        # nrk.no/skole style mediaId:
        media_id_match = re.search("(^|mediaId=)([0-9]+)($|&)", passed_string)
        if media_id_match:
            program_id = get_program_id_from_media_id(media_id_match.group(2))
        else:
            program_id = get_program_id_from_html(passed_string)
    return program_id


def main(programs):
    print("NRK Download {}\n".format(VERSION))
    for i, program in enumerate(programs):
        print(u"Downloading {} of {}:".format(i+1, len(programs)))
        program_id = get_program_id(program)
        if program_id:
            download(program_id)
        else:
            error(u"Could not parse program ID from '{}'".format(program))
        

def get_argument_parser():
    parser = argparse.ArgumentParser(description='Python script for downloading video and audio from NRK (Norwegian Broadcasting Corporation).')
    parser.add_argument("PROGRAMS", type=str, nargs="+", help="A list of URLs or program IDs to download")
    return parser


if __name__ == "__main__":
    programs = get_argument_parser().parse_args().PROGRAMS
    main(programs)
