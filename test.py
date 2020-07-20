import os
import sys
import threading
import requests
import pathlib
import json
import re
from copy import deepcopy
from PayloadSource import PayloadSource, PayloadFactory
from typing import List, Dict, Tuple

def patchMatch(orig:str, values:List[str]) -> Tuple[bool, str]:
    restr = r'(?:§)(\d*)(?:§)'
    match = re.finditer(restr, v)
    if match is None:
        return (False, None)
    
    newText = str(orig)
    for m in match:
        id = int(m.groups()[0])
        if len(values) <= id:
            raise IndexError("payload id {} missing from subtitution list".format(id))

        newText = newText.replace(m.group(), values[id])
    return (True, newText)

if __name__ == "__main__":
    v = "token=PYrbHMSZKF1vNJFNjAjF2y3Z625leKsnMAwpnjmi&email=§1§&password=§2§&d=0"
    b, t = patchMatch(v, ["egy", "ketto", "harom"])
    print("{} -> {}".format(b, t))
