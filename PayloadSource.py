import os
import sys
import threading
from time import sleep
from queue import Queue
from time import sleep
from typing import List, Dict, Tuple, Iterator


class PayloadSource:
    def __init__(self, content: str):
        self._content = content

    def getPayload(self):
        """ Read 1 line from the payload database """
        return self._content

    def isEOF(self):
        return True

    def getError(self):
        return (0, "")

    def reset(self):
        pass


class FilePayloadSource(PayloadSource):
    def __init__(self, content: str):
        PayloadSource.__init__(self, content)
        if not os.path.exists(content):
            raise FileNotFoundError(content)

        self.__file = None
        self.__iseof = False
        self.__mtx = threading.Lock()
        self.__error = (0, "")

    def getPayload(self) -> str:
        if self.__file == None:
            self.__iseof = False
            try:
                self.__file = open(self._content, "r")

            except Exception as ex:
                self.__error = (
                    -1,
                    "File '{}' cannot be opened: {}".format(self._content, ex),
                )
                self.__file = None
                return None
        try:
            self.__error = (0, "")
            line = self.__file.readline()
            if len(line) == 0:
                self.__iseof = True

        except Exception as ex:
            self.__error = (-2, "Cannot read from file '{}'".format(self._content))
            self.__iseof = True

        if self.__iseof == True:
            self.__file.close()
            self.__file = None
            if self.__error[0] < 0:
                return None

        return line.replace("\n", "").replace("\r", "")

    def reset(self):
        if self.__file != None:
            self.__file.close()
            self.__file = None

    def isEOF(self):
        return self.__iseof

    def getError(self):
        return self.__error


class PayloadFactory:
    ThreadCount = 1

    @staticmethod
    def createPayloadSource(content: str):
        offset = content.find(":") + 1
        if content.lower().startswith("file:"):
            return FilePayloadSource(content[offset:])
        elif content.lower().startswith("static:"):
            return PayloadSource(content[offset:])
        elif content.lower().startswith("sequence:"):
            return PayloadSource(content[offset:])
        else:
            return PayloadSource(content)


class PayloadServer:
    def __init__(self, payloads: List[List[PayloadSource]], locked: bool = False):
        self.__prefetch = Queue(PayloadFactory.ThreadCount * 3)
        self.__stopEvent = threading.Event()
        self.__fillEvent = threading.Event()  # set if source queues need to be filled
        self.__payloadSources: List[List[PayloadSource]] = []
        self.__iterPS: List[Iterator[PayloadSource]] = []
        self.__activePS: List[PayloadSource] = []
        self.__lastPayload: List[str] = []
        self.__status = 1
        for i in range(len(payloads)):
            pli = payloads[i]
            pl: list[PayloadSource] = []
            j = 0
            for p in pli:
                pl.append(PayloadFactory.createPayloadSource(p))
                j += 1
            self.__payloadSources.append(pl)
            self.__iterPS.append(iter(pl))
            aps = next(self.__iterPS[i])
            self.__activePS.append(aps)
            self.__lastPayload.append(None)

        self.__fillEvent.set()
        self.__threadHandle = threading.Thread(
            target=PayloadServer.__threadFunc, args=(self,), name="fill"
        )
        self.__threadHandle.start()

    def __threadFunc(self):
        while not self.__stopEvent.is_set():
            self.__fillEvent.wait()
            if self.__stopEvent.is_set():
                break

            self.__fillEvent.clear()

            payloadsNeeded = self.__prefetch.maxsize - self.__prefetch.qsize()
            try:
                for _ in range(payloadsNeeded):
                    newValues = [""] * len(self.__payloadSources)
                    endOfList = [False] * len(self.__payloadSources)
                    useLast = False
                    for i in reversed(range(len(self.__payloadSources))):
                        if useLast and self.__lastPayload[i] != None:
                            newValues[i] = self.__lastPayload[i]
                            continue

                        while True:
                            apl = self.__activePS[i]
                            npl = apl.getPayload()

                            if npl is None:
                                npl = "ERROR: {}".format(apl.getError())
                                sleep(1)
                            elif apl.isEOF():
                                try:
                                    # end of PS, switch to next one
                                    apl.reset()
                                    apl = next(self.__iterPS[i])
                                    self.__activePS[i] = apl
                                except StopIteration:
                                    # on end of list, start over from beginning
                                    endOfList[i] = True
                                    self.__iterPS[i] = iter(self.__payloadSources[i])
                                    self.__activePS[i] = next(self.__iterPS[i])
                                    if i == 0:
                                        # end of all
                                        self.__status = 0
                                        self.__stopEvent.set()
                                        break
                            else:
                                self.__lastPayload[i] = npl
                                newValues[i] = npl
                                useLast = not endOfList[i]
                                break
                    if self.__stopEvent.is_set():
                        break
                    self.__prefetch.put(newValues)

            except Exception as ex:
                print("Error during filling queue: {}".format(ex))

    def stop(self):
        self.__stopEvent.set()
        self.__fillEvent.set()
        if self.__threadHandle != None:
            self.__threadHandle.join()
            self.__threadHandle = None

    def hasFinished(self):
        return self.__status == 0 and self.__prefetch.qsize() == 0

    def getPayloads(self) -> List[str]:
        s = self.__prefetch.qsize()
        if s < self.__prefetch.maxsize / 2:
            self.__fillEvent.set()

        if s > 0:
            return self.__prefetch.get()
        else:
            return None

