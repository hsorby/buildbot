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
import requests

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
        changes = []
        event_type = request.getHeader('x-github-event')
        if event_type == 'ping':
            return (None, 'git')
        elif event_type == 'pull_request':
            payload = json.loads(request.args['payload'][0])
            action = payload['action']
            if action == 'synchronize' or action == 'opened':
                # from payload get events list from event originating repo
                changes = get_pull_changes(payload)
        elif event_type == 'push':
            payload = json.loads(request.args['payload'][0])
            user = payload['repository']['owner']['name']
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
        else:
            return (None, 'git')

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
        refname = payload['ref']

        # We only care about regular heads, i.e. branches
        match = re.match(r"^refs\/heads\/(.+)$", refname)
        if not match:
            log.msg("Ignoring refname `%s': Not a branch" % refname)
            return []

        branch = match.group(1)
        if 'after' in payload and re.match(r"^0*$", payload['after']):
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
                    author   = commit['author']['name'] 
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
        
def get_pull_changes(payload):
    """
    Get the changes from the associated push for the given payload.
    """
    changes = []
    
    project = ''
    commit = get_head_commit(payload)
    if commit:
        branch = payload['pull_request']['head']['ref']
        repo_url = payload['pull_request']['head']['repo']['ssh_url']
        files = []
        for commit_file in commit['files']:
            files.append(commit_file['filename'])
            
        # A really rough conversion from one data format to another
        commit_date = commit['commit']['committer']['date']
        if commit_date.endswith('Z'):
            commit_date = commit_date.replace('Z', '+00:00')
        when =  convertTime(commit_date)
        log.msg("New revision: %s on %s" % (commit['sha'][:8], repo_url))
        chdict = dict(
            author   = commit['commit']['author']['name'] 
                        + " <" + commit['commit']['author']['email'] + ">",
            files    = files,
            comments = commit['commit']['message'],
            revision = commit['sha'],
            when     = when,
            branch   = branch,
            properties = {'statuses_url': str(payload['pull_request']['statuses_url']),
                          'owner': str(payload['repository']['owner']['login']),
                          'repo': str(payload['repository']['name']),
                          'pull_number': str(payload['number'])}, #, 'Change']},
            revlink  = commit['url'], 
            repository = repo_url,
            project  = project)

        changes.append(chdict) 

    return changes

def get_head_commit(payload):
    """
    Get whatever we need from this payload
    """
    commits_url = payload['pull_request']['head']['repo']['commits_url']
    pull_request_head = payload['pull_request']['head']['sha']
    commits_url = commits_url.replace('{/sha}', '/{sha}')
    commit_url = commits_url.format(sha=pull_request_head)
    commit_response = requests.get(commit_url)
    if commit_response.status_code == 200:
        commit = commit_response.json()
        return commit

