# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

#!/usr/bin/env python
"""
github_buildbot.py is based on git_buildbot.py

github_buildbot.py will determine the repository information from the JSON 
HTTP POST it receives from github.com and build the appropriate repository.
If your github repository is private, you must add a ssh key to the github
repository for the user who initiated the build on the buildslave.

"""

import re
import datetime
from twisted.python import log
import calendar

try:
    import json
    assert json
except ImportError:
    import simplejson as json

# python is silly about how it handles timezones
class fixedOffset(datetime.tzinfo):
    """
    fixed offset timezone
    """
    def __init__(self, minutes, hours, offsetSign = 1):
        self.minutes = int(minutes) * offsetSign
        self.hours   = int(hours)   * offsetSign
        self.offset  = datetime.timedelta(minutes = self.minutes,
                                         hours   = self.hours)

    def utcoffset(self, dt):
        return self.offset

    def dst(self, dt):
        return datetime.timedelta(0)
    
def convertTime(myTestTimestamp):
    #"1970-01-01T00:00:00+00:00"
    matcher = re.compile(r'(\d\d\d\d)-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)([-+])(\d\d):(\d\d)')
    result  = matcher.match(myTestTimestamp)
    (year, month, day, hour, minute, second, offsetsign, houroffset, minoffset) = \
        result.groups()
    if offsetsign == '+':
        offsetsign = 1
    else:
        offsetsign = -1
    
    offsetTimezone = fixedOffset( minoffset, houroffset, offsetsign )
    myDatetime = datetime.datetime( int(year),
                                    int(month),
                                    int(day),
                                    int(hour),
                                    int(minute),
                                    int(second),
                                    0,
                                    offsetTimezone)
    return calendar.timegm( myDatetime.utctimetuple() )

def getChanges(request, options = None):
        """
        Reponds only to POST events and starts the build process
        
        :arguments:
            request
                the http request object
        """
        print 'here I am', 'in getChanges()'
        event_type = request.getHeader('x-github-event')
        if event_type == 'ping':
            return (None, 'git')
        elif event_type == 'pull_request':
            print 'What do we do now'
            return (None, 'git')
        elif event_type != 'push':
            return (None, 'git')

        print request.getAllHeaders()
        print '===================='
        print dir(request)
        print request.args
        payload = json.loads(request.args['payload'][0])
        print payload
        print payload.keys()
        print payload['repository']
        print payload['repository'].keys()
        print payload['repository']['owner']
        print payload['repository']['owner'].keys()
        print payload['repository']['owner']['login']
        print payload['repository']['owner']['id']
        print payload['repository']['name']
        print payload['repository']['url']
        if 'name' in payload['repository']['owner']:
            user = payload['repository']['owner']['name']
        elif 'login' in payload['repository']['owner']:
            user = payload['repository']['owner']['login']
        else:
            user = 'bob'
        #user = payload['repository']['owner']['name']
        repo = payload['repository']['name']
        repo_url = payload['repository']['url']
        project = request.args.get('project', None)
        if project:
            project = project[0]
        elif project is None:
            project = ''
        # This field is unused:
        #private = payload['repository']['private']
        changes = process_change(payload, user, repo, repo_url, project)
        log.msg("Received %s changes from github" % len(changes))
        return (changes, 'git')

def process_change(payload, user, repo, repo_url, project):
        """
        Consumes the JSON as a python object and actually starts the build.
        
        :arguments:
            payload
                Python Object that represents the JSON sent by GitHub Service
                Hook.
        """
        changes = []
        newrev = payload['after']
        refname = payload['ref']

        # We only care about regular heads, i.e. branches
        match = re.match(r"^refs\/heads\/(.+)$", refname)
        if not match:
            log.msg("Ignoring refname `%s': Not a branch" % refname)
            return []

        branch = match.group(1)
        if re.match(r"^0*$", newrev):
            log.msg("Branch `%s' deleted, ignoring" % branch)
            return []
        else: 
            for commit in payload['commits']:
                files = []
                if 'added' in commit:
                    files.extend(commit['added'])
                if 'modified' in commit:
                    files.extend(commit['modified'])
                if 'removed' in commit:
                    files.extend(commit['removed'])
                when =  convertTime( commit['timestamp'])
                log.msg("New revision: %s" % commit['id'][:8])
                chdict = dict(
                    who      = commit['author']['name'] 
                                + " <" + commit['author']['email'] + ">",
                    files    = files,
                    comments = commit['message'], 
                    revision = commit['id'],
                    when     = when,
                    branch   = branch,
                    revlink  = commit['url'], 
                    repository = repo_url,
                    project  = project)
                changes.append(chdict) 
            return changes
        
