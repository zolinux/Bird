# Bird
Lightweight Burpsuite-like intruder without limitation of community edition

usage:
  1. copy raw request data to a file eg. *request.txt*
  ```
    POST /login.php HTTP/1.1
    Host: 10.10.10.10:80
    User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:68.0) Gecko/20100101 Firefox/68.0
    Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8
    Accept-Language: en-US,en;q=0.5
    Accept-Encoding: gzip, deflate
    Referer: http://10.10.10.10:80/login.php
    Content-Type: application/x-www-form-urlencoded
    Content-Length: 37
    Connection: close
    Upgrade-Insecure-Requests: 1
    DNT: 1

    email=§0§&password=§1§
  ```
  2. create a JSON file with the attack details. e.g: login.json
  ``` json
    {
      "payloads": [
          [
              "file:emails.txt"
          ],
          [
              "file:passwords.txt",
              "file:/usr/share/wordlists/rockyou.txt"
          ]
      ],
      "threads": 10,
      "proxy": {
          "http": "127.0.0.1:8080",
          "https":"127.0.0.1:8080"
      }
   ```
   3. start the attack from command line as
   ```
      ./bird.py -j login.json -r request.txt
   ```
