from __future__ import absolute_import
import base64
import traceback
from flask import (Flask, abort, flash, redirect, render_template,
                   request, url_for)
from tasks import fibonacci
from tasks import run_yadage_workflow

app = Flask(__name__)
app.secret_key = "super secret key"

experiment_to_queue = {
    'alice': 'alice-queue',
    'atlas': 'atlas-queue',
    'lhcb': 'lhcb-queue',
    'cms': 'cms-queue',
    'recast': 'recast-queue'
}


def check_fibonacci_workflow(input_file):
    nums = []
    if input_file.find('\n') > 0:
        lines = input_file.split('\n')
        if lines[0].strip() != 'Fibonacci pipeline':
            raise ValueError
        # lines[2] which is the docker image should
        # be checked but since this is a proof of
        # concept we suppose that it exists.
        for pos, line in enumerate(lines[3:]):
            lines[pos+3] = lines[pos+3].strip()
            tmp_nums = []
            for num in line.split(','):
                tmp_nums.append(int(num))
            nums.append(tmp_nums)
    else:
        tmp_nums = []
        for num in input_file.split(','):
            tmp_nums.append(int(num))
        nums.append(tmp_nums)

    return lines[1].strip(), lines[2].strip(), '\n'.join(lines[3:])


@app.route('/fibonacci', methods=['GET', 'POST'])
def fibonacci_endpoint():
    if request.method == 'GET':
        return render_template('bg-form.html')

    # Calculate fibonacci in background
    if request.method == 'POST':
        try:
            if request.json:
                task_weight = request.json['weight']
                queue = experiment_to_queue[request.json['experiment']]
                input_file = base64.decodestring(request.json['input-file'])
                docker_img, cmd, fib_file = check_fibonacci_workflow(
                    input_file
                )

                fibonacci.apply_async(
                    args=[docker_img, cmd, task_weight, fib_file,
                          request.json['experiment']],
                    queue='fibo-{}'.format(queue)
                )
                return 'Workflow successfully launched'
            else:
                task_weight = request.form['weight']
                queue = experiment_to_queue[request.form['experiment']]
                input_file = request.form['input-file']
                docker_img, cmd, fib_file = check_fibonacci_workflow(
                    input_file
                )

                fibonacci.apply_async(
                    args=[docker_img, cmd, task_weight, fib_file,
                          request.form['experiment']],
                    queue='fibo-{}'.format(queue)
                )

                flash('Workflow successfully launched')
                return redirect(url_for('fibonacci_endpoint'))
        except (KeyError, ValueError):
            traceback.print_exc()
            abort(400)


@app.route('/yadage', methods=['GET', 'POST'])
def yadage_endpoint():
    if request.method == 'POST':
        try:
            if request.json:
                toplevel = request.json['toplevel']
                workflow = request.json['workflow']
                parameters = request.json['parameters']
                queue = experiment_to_queue[request.json['experiment']]

                run_yadage_workflow.apply_async(
                    args=[toplevel, workflow, parameters],
                    queue='yadage-{}'.format(queue)
                )

                return 'Workflow successfully launched'

        except (KeyError, ValueError):
            traceback.print_exc()
            abort(400)


if __name__ == '__main__':
    app.run(debug=True, port=5000,
            host='0.0.0.0')
