# -*- coding: utf-8 -*-
"""
    This program is free software; you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation; either version 3 of the License,
    or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
    See the GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program; if not, see <http://www.gnu.org/licenses/>.

    @author: zoidberg
"""

import re
from module.plugins.Hoster import Hoster
from module.network.RequestFactory import getURL
from module.plugins.ReCaptcha import ReCaptcha

def getInfo(urls):
    result = []

    for url in urls:
        html = getURL(url, decode=True)
        if re.search(MediafireCom.FILE_OFFLINE_PATTERN, html):
            # File offline
            result.append((url, 0, 1, url))
        else:
            # Get file info
            name, size = url, 0

            found = re.search(MediafireCom.FILE_SIZE_PATTERN, html)
            if found is not None:
                size, units = found.group(1), found.group(2).replace('k','K')
                size = float(size) * 1024 ** {'KB': 1, 'MB': 2, 'GB': 3}[units]

            found = re.search(MediafireCom.FILE_NAME_PATTERN, html)
            if found is not None:
                name = found.group(1)

            if found or size > 0:
                result.append((name, size, 2, url))
    yield result

def replace_eval(js_expr):
    return js_expr.replace(r'eval("', '').replace(r"\'", r"'").replace(r'\"', r'"')

class MediafireCom(Hoster):
    __name__ = "MediafireCom"
    __type__ = "hoster"
    __pattern__ = r"http://(?:\w*\.)*mediafire\.com/.*"
    __version__ = "0.61"
    __description__ = """Mediafire.com plugin - free only"""
    __author_name__ = ("zoidberg")
    __author_mail__ = ("zoidberg@mujmail.cz")

    PAGE1_FUNCTION_PATTERN = r"function %s\(qk,pk1\)\{if[^']*'loadingicon'\);[^;]*; (.*?)eval"
    PAGE1_KEY_PATTERN = ";break;}\s*(\w+='';\w+=unescape.*?)eval\("
    PAGE1_RESULT_PATTERN = r"(\w+)\('(?P<qk>[^']+)','(?P<pk1>[^']+)'\)"
    PAGE1_DIV_PATTERN = r'getElementById\("(\w{32})"\)'
    PAGE1_PKR_PATTERN = r"pKr='([^']+)';"
    RECAPTCHA_PATTERN = r'src="http://api.recaptcha.net/challenge?k=([^"]+)">'
    PAGE1_ACTION_PATTERN = r'<link rel="canonical" href="([^"]+)"/>'

    PAGE2_VARS_PATTERN = r'<script language="Javascript"><!--\s*(var.*?unescape.*?)eval\('
    PAGE2_DZ_PATTERN = r'break;case 15:(.*)</script>'
    PAGE2_LINK_PATTERN = r"(\w+='';\w+=unescape.*?)eval\(\w+\);(.{0,10}href=[^>]*>)?"
    FINAL_LINK_PATTERN = r'parent.document.getElementById\(\'(\w{32})\'\).*(http://[^"]+)" \+(\w+)\+ "([^"]+)">'

    FILE_NAME_PATTERN = r'<META NAME="description" CONTENT="([^"]+)"/>'
    FILE_SIZE_PATTERN = r'<div style="font-size:14px;padding-top:12px;color:#777;">\(([0-9.]+) (kB|KB|MB|GB)\)</div>'
    FILE_OFFLINE_PATTERN = r'class="error_msg_title"> Invalid or Deleted File. </div>'

    def setup(self):
        self.multiDL = False

    def process(self, pyfile):
        self.html = self.load(pyfile.url, decode=True)
        self.getFileInfo(pyfile)
        self.handleFree()

    def getFileInfo(self, pyfile):
        if re.search(self.FILE_OFFLINE_PATTERN, self.html): self.offline()
        
        found = re.search(self.FILE_NAME_PATTERN, self.html)
        if not found: self.fail("Parse error (file name)")
        pyfile.name = found.group(1)

        found = re.search(self.FILE_SIZE_PATTERN, self.html)
        if found:
            size, units = found.group(1), found.group(2).replace('k','K')
            pyfile.size = float(size) * 1024 ** {'KB': 1, 'MB': 2, 'GB': 3}[units]

    def handleFree(self):
        found = re.search(self.RECAPTCHA_PATTERN, self.html)
        if found:
            captcha_action = re.search(self.PAGE1_ACTION_PATTERN, self.html).group(1)
            captcha_key = found.group(1)
            recaptcha = ReCaptcha(self)
            captcha_challenge, captcha_response = recaptcha.challenge(captcha_key)
            self.html = self.load(captcha_action, post = {
                "recaptcha_challenge_field": captcha_challenge,
                "recaptcha_response_field": captcha_response
                })

        found = re.search(self.PAGE1_KEY_PATTERN, self.html)
        if found:
            result = self.js.eval(found.group(1))
            found = re.search(self.PAGE1_RESULT_PATTERN, result)
        else:
            self.retry(3, 0, "Parse error (KEY)")

        try:
            param_dict = found.groupdict()
            param_dict['r'] = re.search(self.PAGE1_PKR_PATTERN, self.html).group(1)
            self.logDebug(param_dict)
            key_func = found.group(1)
            self.logDebug("KEY_FUNC: %s" % key_func)

            found = re.search(self.PAGE1_FUNCTION_PATTERN % key_func, self.html)
            result = self.js.eval(found.group(1))
            key_div = re.search(self.PAGE1_DIV_PATTERN, result).group(1)
            self.logDebug("KEY_DIV: %s" % key_div)
        except Exception, e:
            self.logError(e)
            self.retry(3, 0, "Parse error (KEY DIV)")

        self.html = self.load("http://www.mediafire.com/dynamic/download.php", get=param_dict)
        js_expr = replace_eval(re.search(self.PAGE2_VARS_PATTERN, self.html).group(1))
        result = self.js.eval(js_expr)
        var_list = dict(re.findall("([^=]+)='([^']+)';", result))

        page2_dz = replace_eval(re.search(self.PAGE2_DZ_PATTERN, self.html, re.DOTALL).group(1))

        final_link = None
        for link_enc in re.finditer(self.PAGE2_LINK_PATTERN, page2_dz):
            #self.logDebug("LINK_ENC: %s..." % link_enc.group(1)[:20])
            try:
                link_dec = self.js.eval(link_enc.group(1))
            except Exception, e:
                self.logError("Unable to decrypt link %s" % link_enc.group(1)[:20])
                self.logError(e)
                self.logDebug(link_enc.group(1))
                continue

            #self.logDebug("LINK_DEC: %s" % link_dec)
            if link_enc.group(2): link_dec = link_dec + replace_eval(link_enc.group(2))

            found = re.search(self.FINAL_LINK_PATTERN, link_dec)
            if found:
                if found.group(1) == key_div:
                    final_link = found.group(2) + var_list[found.group(3)] + found.group(4)
                    break
            else:
                self.logDebug("Link not found in %s..." % link_dec)
        else:
            self.fail("Final link not found")

        self.logDebug("FINAL LINK: %s" % final_link)
        self.download(final_link)