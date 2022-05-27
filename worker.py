import requests
import time
import uuid
import os

master_ip = os.environ.get('MASTER_IP')
master_ip = 'localhost'

PORT = 5005

import hashlib

def work(buffer, iterations):
     output = hashlib.sha512(buffer).digest()
     for i in range(iterations - 1):
          output = hashlib.sha512(output).digest()
     return output


def worker():
     while True:
          try:
               # get task task
               res = requests.get(f'http://{master_ip}:5004/getWork')
          except:
               time.sleep(5)
               continue
          if res.status_code != 200:
               time.sleep(2)
               continue

          task = res.json()['job']

          if task is None:
               time.sleep(2)
               continue

          task_id, task_time, buffer, iterations = task

          result = work(buffer.encode('utf-8'), iterations)

          # inform done task
          res = requests.post(f'http://{master_ip}:5004/finishWork', data={'task_id': task_id, 'result': result})

worker()