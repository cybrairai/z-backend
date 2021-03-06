import sys
import os
import re
import subprocess
import json
import settings


def get_int(val):
    if val is None:
        return 0
    try:
        return int(val)
    except ValueError:
        return 0


class ZRetrieve:
    @staticmethod
    def exportJSON(data):
        """
        1. load the existing data
        2. merge this data in the existing list
        3. save new list
        """

        with open('reports.json', 'r+') as f:
            fdata = f.read()
            f.seek(0)

            if len(fdata) == 0:
                x = {'list': []}
            else:
                x = json.loads(fdata)

            x['list'].append(data)

            x = json.dumps(x)
            f.write(x)
            f.truncate()

    @staticmethod
    def get_z_name(zdata):
        z_name = str(zdata['z'])
        if z_name.isdigit():
            z_name = "Z " + z_name
        return z_name

    @staticmethod
    def get_report_filename(zdata):
        z_name = ZRetrieve.get_z_name(zdata)
        prettydate = ''.join(zdata['date'][-10:].split('.')[::-1])
        prettybuilddate = ''.join(zdata['builddate'][:10].split('.')[::-1]) + '_' + zdata['builddate'][11:13] + zdata['builddate'][14:16]
        filename = '%s-%s-%s' % (prettydate, re.sub(r'[^a-zA-Z0-9]', '_', z_name), prettybuilddate)
        return filename


class ZTemplate:
    def __init__(self):
        self.template = ZTemplate.get_template()

    def generate(self, zdata, filename):
        tex = self.template

        ztext = ZRetrieve.get_z_name(zdata)
        tex = tex.replace("VAR-ZNR", ZTemplate.safestring(ztext))

        tex = tex.replace("VAR-RESPONSIBLE", ZTemplate.safestring(zdata['responsible']))
        tex = tex.replace("VAR-TYPE", ZTemplate.safestring(zdata['type']))
        tex = tex.replace("VAR-DATE", ZTemplate.safestring(zdata['date']))
        tex = tex.replace("VAR-BUILDDATE", ZTemplate.safestring(zdata['builddate']))
        tex = tex.replace("VAR-COMMENT", ZTemplate.safestring(zdata['comment']).replace("\n", "\\\\\n"))

        trans = "\n\cline{3-6}".join(ZTemplate.get_trans(zdata['sales'], True)) \
              + "\n\cline{3-6}".join(ZTemplate.get_trans(zdata['debet']))
        tex = tex.replace("VAR-SALES-AND-DEBET", trans)

        tex = tex.replace("VAR-CASH", ZTemplate.get_cash_table(zdata['cash']))

        ZTemplate.generate_pdf(tex, filename)

    @staticmethod
    def get_template(file='template.tex'):
        with open(file, 'r') as f:
            data = f.read()
        return data

    @staticmethod
    def safestring(data):
        CHARS = {
            '&':  r'\&',
            '%':  r'\%',
            '$':  r'\$',
            '#':  r'\#',
            '_':  r'\_',  # r'\letterunderscore{}',
            '{':  r'\{',  # r'\letteropenbrace{}',
            '}':  r'\}',  # r'\letterclosebrace{}',
            '~':  r'\~',  # r'\lettertilde{}',
            '^':  r'\^',  # r'\letterhat{}',
            '\\': r'\\',  # r'\letterbackslash{}',
        }
        return "".join([CHARS.get(char, char) for char in str(data).strip()])

    @staticmethod
    def get_trans(data, addsum=0):
        trans = []
        sum = 0
        for r in data:
            t = Transaction(r[0])

            mva = ""
            if t.vat != 0:
                if t.vat in settings.VAT_CODES:
                    mva = "%s (%d\\%%)" % (ZTemplate.safestring(t.vat), settings.VAT_CODES[t.vat])
                else:
                    mva = ZTemplate.safestring(t.vat) + '\\% (?)'

            trans.append("\\footnotesize{%s} & \\footnotesize{%s} & \\small{%s} & %s & %s & \\footnotesize{%s} \\\\" %
                         (t.project or "", mva, ZTemplate.safestring(t.type), ZTemplate.safestring(t.account),
                          ZTemplate.safestring(r[2]), ZTemplate.safestring(r[1])))
            sum += get_int(r[2])
        if addsum:
            trans.append("&&&& \\textbf{%d} & \\textbf{Sum salg} \\\\[3mm]" % sum)
        return trans

    @staticmethod
    def get_cash_table(data):
        ret = []
        t = [1, 5, 10, 20, 50, 100, 200, 500, 1000]
        sum = 0
        sum_start = 0
        sum_end = 0
        for i, start in enumerate(data['start']):
            start = get_int(start)
            end = get_int(data['end'][i])

            x = end-start
            amount = x*t[i]
            ret.append("%s & %s & %s & %s & %s \\\\" %
                       (t[i], start, end, x, amount))
            sum += amount
            sum_start += start*t[i]
            sum_end += end*t[i]

        ret.append("\\textbf{Sum} & %d & %d & & %d \\\\" %
                   (sum_start, sum_end, sum))

        return "\n\hline".join(ret)

    @staticmethod
    def generate_pdf(data, filename):
        with open('archive/%s.tex' % filename, 'w') as f:
            f.write(data)

        p = subprocess.Popen(["pdflatex", "%s.tex" % filename], stdout=subprocess.PIPE, cwd=os.path.abspath('archive'))
        out, err = p.communicate()


# variable data is a associative array with the following keys:
#   z => "Znr" in the spreadsheet (can be text, but excludes "Z" char)
#   date => date of the z report
#   builddate => current date (when exported)
#   responsible => who's in charge of the Z
#   type => the type of event (user provided, e.g. "Kafé")
#   cash => [
#     start => array of cash when started, first element is 1, second 5, 10, 20, 50 ...
#     end   => array of cash when ended (same structure as above)
#   ]
#   sales => [
#     array(account details, account text, value) e.g. ("K-3014-25", "Salg, mineralvann", 106),
#                                                (beware: ^old format. new format: "25-K-3014-40404")
#     ...
#   ]
#   debet => same as sales
#   comment => user provided comment


class Transaction:
    def __init__(self, data):
        # format: [vatcode]-K/D-account-[project]
        # (old format: K/D-account-vat)

        # match again old format
        m = re.match(r'^([KD])-([\d_]+)(?:-(25|15|__))?$', data)
        if m is not None:
            self.type = m.group(1)
            self.account = m.group(2)
            self.vat = get_int(m.group(3)) or 0
            self.project = 0

        else:
            # new format
            m = re.match(r'^(?:(\d+)-)?([KD])-([\d_]+)(?:-([\d_]+))?$', data)
            if m is None:
                raise ValueError("Invalid data when parsing Trans: %s" % data)
            self.type = m.group(2)
            self.account = m.group(3)
            self.vat = get_int(m.group(1)) or 0
            self.project = get_int(m.group(4)) or 0

