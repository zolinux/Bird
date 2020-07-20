#! /usr/bin/env python3
import os
import sys
import threading
import requests
import json
import re
import traceback
from copy import deepcopy
from time import sleep
from PayloadSource import PayloadSource, PayloadFactory, PayloadServer
from typing import List, Tuple
from argparse import ArgumentParser

VERSION = "0.1.0"


class Request:
    __host: str
    __url: str
    __proxies: dict
    __placeholders: int
    __content: dict

    def __init__(self, content):
        self.__type = requests.get
        self.__host = ""
        self.__url = ""
        self.__placeholders = 0
        self.__proxies = {}
        self.__content = {"header": {}, "cookies": {}, "data": []}

        if isinstance(content, list):
            self.setContent(content)
        else:
            raise NotImplementedError("only list supported")

    def setProxy(self, proxies: dict):
        self.__proxies = proxies

    def setContent(self, lines: List[str]):
        url = ""
        protocol = ""
        parseData = False

        for line in lines:
            if line.strip() == "":
                parseData = True
                continue

            if line.startswith("#"):
                continue

            l = line.lower()
            connspec = False
            if l.startswith("get"):
                self.__type = requests.get
                connspec = True
            elif l.startswith("post"):
                self.__type = requests.post
                connspec = True
            elif l.startswith("head"):
                self.__type = requests.head
                connspec = True
            elif l.startswith("options"):
                self.__type = requests.options
                connspec = True

            if connspec:
                url = re.search(r"^(?:\w* )(\S+)", line).groups()[0]
                protocol = re.search(r"(http\w*)", l).group() + "://"
                continue

            # ToDo: count and check placeholders
            # placeholders = re.search(r'')
            i = line.find(":")
            if i > 0 and not parseData:
                key = line[0:i].strip()
                val = line[i + 1 :].strip()
                k = key.lower()

                if k == "host":
                    self.__host = val
                elif k == "cookie":
                    for piece in val.split(";"):
                        ck, cv = piece.split("=", 1)
                        self.__content["cookies"][ck.strip()] = cv.strip()
                else:
                    self.__content["header"][key] = val

            else:
                # body data comes here (no colon allowed -> %3A subtituted)
                if len(line.strip()) > 0:
                    self.__content["data"].append(line)

        if len(url) > 0:
            self.__url = protocol + self.__host + url

    def setCookie(self, cookieString: str):
        cookies = cookieString.split(";")
        for ck in cookies:
            k, v = ck.split("=", 1)
            self.__content["cookies"][k.strip()] = v.strip()

    @staticmethod
    def __patchMatch(orig: str, values: List[str]) -> Tuple[bool, str]:
        restr = r"(?:§)(\d*)(?:§)"
        match = re.finditer(restr, orig)
        if match is None:
            return (False, orig)

        newText = str(orig)
        for m in match:
            id = int(m.groups()[0])
            if len(values) <= id:
                raise IndexError(
                    "payload id {} missing from subtitution list".format(id)
                )

            newText = newText.replace(m.group(), values[id])
        return (True, newText)

    def request(self, values: List[str], port: int = 0) -> requests.Response:
        r = deepcopy(self.__content)
        if port == 0:
            if self.__url.startswith("https"):
                port = 443
            else:
                port = 80

        patched, url = Request.__patchMatch(self.__url, values)

        for k, v in r["header"].items():
            patched, text = Request.__patchMatch(v, values)
            if patched:
                r["header"][k] = text

        for k, v in r["cookies"].items():
            patched, text = Request.__patchMatch(v, values)
            if patched:
                r["cookies"][k] = text

        for idx in range(len(r["data"])):
            patched, text = Request.__patchMatch(r["data"][idx], values)
            if patched:
                r["data"][idx] = text

        resp = self.__type(
            url,
            data="".join(r["data"]),
            proxies=self.__proxies,
            cookies=r["cookies"],
            headers=r["header"],
            timeout=5,
        )
        return resp


class Bird:
    __threadHandles: List[threading.Thread]

    def __init__(self, settings: dict, req: Request):
        self.__json = settings
        self.__request = req
        self.__responseCount = 0
        self.__threads = 1
        self.__quitEvent = threading.Event()  # set if application should quit
        self.__threadHandles = []
        self.__mtx = threading.Lock()
        self.__responseMtx = threading.Lock()
        # self.__cond = threading.Condition(self.__mtx)

        if "proxy" in self.__json.keys():
            self.__request.setProxy(self.__json["proxy"])

        if "threads" in settings.keys():
            self.__threads = settings["threads"]

        if not "payloads" in settings.keys():
            raise ModuleNotFoundError("missing payloads from JSON")

        # ToDo: throw error if payload set count != placeholder count
        payloads = settings["payloads"]
        PayloadFactory.ThreadCount = self.__threads

        # create Payload sources
        self.__payloadServer = PayloadServer(payloads)

    def __handleResponse(self, response: requests.Response, values: List[str]):
        response_ = "{:3d} {:4d}ms {:5d} {}".format(
            response.status_code,
            round(response.elapsed.total_seconds() * 1000),
            len(response.content),
            values,
        )
        with self.__responseMtx:
            print("{:6d} ".format(self.__responseCount) + response_)
            self.__responseCount += 1

    def __abort(self):
        with self.__mtx:
            if not self.__quitEvent.is_set():
                self.__quitEvent.set()
                self.__payloadServer.stop()

    def __threadFunc(self):
        young = True
        vals: list[str]
        while not self.__quitEvent.is_set():
            vals = self.__payloadServer.getPayloads()
            if vals is None:
                if not self.__payloadServer.hasFinished() and not young:
                    print(
                        "Worker ran out of data, try to increase thread number",
                        file=sys.stderr,
                    )
                sleep(0.25)
                continue

            trials = 0
            err = None
            while not self.__quitEvent.is_set():
                try:
                    trials += 1
                    resp = self.__request.request(vals, 0)
                    self.__handleResponse(resp, vals)
                    resp = None
                    young = False
                    break

                except Exception as e:
                    err = e

                if err != None:
                    if trials >= 5:
                        print("Error: {}".format(err), file=sys.stderr)
                        self.__abort()
                    else:
                        sleep(1)
                        err = None

    def fly(self) -> int:
        # self.__cond.notify()
        # self.__cond.acquire()
        i = 0
        while i < self.__threads:
            th = threading.Thread(
                target=Bird.__threadFunc, args=(self,), name="Work{}".format(i)
            )
            th.start()
            self.__threadHandles.append(th)
            i += 1

        while not self.__payloadServer.hasFinished() and not self.__quitEvent.is_set():
            try:
                sleep(0.25)
            except KeyboardInterrupt:
                break
            except Exception as ex:
                print("Error: {}".format(str(ex)), file=sys.stderr)

        self.__quitEvent.set()
        for t in self.__threadHandles:
            t.join()
            t = None
        self.__payloadServer.stop()
        return 0


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.description = """Intruder a'la BurpSuit without the any limitation"""
    parser.add_argument("--version", action="version", version="%(prog)s " + VERSION)
    parser.add_argument(
        "-c", "--cookie", dest="cookies", action="append", metavar=("cookie")
    )
    parser.add_argument(
        "-j",
        "--json",
        metavar=("file"),
        help="JSON file that describes the context of the request",
    )
    parser.add_argument(
        "-r",
        "--request",
        metavar=("file"),
        help="File with request data (saved from Burpsuit), placeholders are identified by §0§ with the index inside",
    )

    args = parser.parse_args()
    showHelp = False

    if args.json == None:
        print("Missing required argument: --json")
        showHelp = True
    if args.request == None:
        print("Missing required argument: --request")
        showHelp = True

    if showHelp:
        parser.print_help()
        exit(2)

    try:
        f = open(args.json, "r")
        settings = json.load(f)
        if settings == None:
            raise AttributeError("invalid JSON file")

        f.close()

        f = open(args.request, "r")
        req = Request(f.readlines())
        f.close()

        if args.cookies != None:
            for ck in args.cookies:
                req.setCookie(ck)

        bird = Bird(settings, req)

    except FileNotFoundError as exf:
        print("Error: file {} could not be opened!".format(exf.filename))
        exit(3)
    except Exception as ex:
        traceback.print_exc()
        exit(2)

    exit(bird.fly())

