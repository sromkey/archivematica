# This file is part of Archivematica.
#
# Copyright 2010-2013 Artefactual Systems Inc. <http://artefactual.com>
#
# Archivematica is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Archivematica is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Archivematica.  If not, see <http://www.gnu.org/licenses/>.

import ast
import copy
import httplib
import json
import logging
import os
import requests
import slumber
import sys
import uuid

from django.contrib import messages
from django.conf import settings
from django.core.urlresolvers import reverse
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.shortcuts import render, redirect
from django.template import RequestContext
from elasticsearch import Elasticsearch, ElasticsearchException
from lazy_paged_sequence import LazyPagedSequence

from main import models
from components.archival_storage import forms
from components import advanced_search
from components import decorators
from components import helpers
sys.path.append("/usr/lib/archivematica/archivematicaCommon")
import databaseFunctions
import elasticSearchFunctions
import storageService as storage_service

logger = logging.getLogger('archivematica.dashboard')

AIPSTOREPATH = '/var/archivematica/sharedDirectory/www/AIPsStore'

AIP_STATUS_DESCRIPTIONS = {
    'UPLOADED': 'Stored',
    'DEL_REQ':  'Deletion requested'
}

@decorators.elasticsearch_required()
def overview(request):
    return list_display(request)

def search(request):
    # FIXME there has to be a better way of handling checkboxes than parsing
    # them by hand here, and displaying 'checked' in
    # _archival_storage_search_form.html
    # Parse checkbox for file mode
    yes_options = ('checked', 'yes', 'true', 'on')
    if request.GET.get('filemode', '') in yes_options:
        file_mode = True
        checked_if_in_file_mode = 'checked'
        items_per_page = 20
    else:  # AIP list
        file_mode = False
        checked_if_in_file_mode = ''
        items_per_page = 10

    # Parse checkbox for show AICs
    show_aics = ''
    if request.GET.get('show_aics', '') in yes_options:
        show_aics = 'checked'

    # get search parameters from request
    queries, ops, fields, types = advanced_search.search_parameter_prep(request)
    logger.debug('Queries: %s, Ops: %s, Fields: %s, Types: %s', queries, ops, fields, types)

    # redirect if no search params have been set
    if 'query' not in request.GET:
        return helpers.redirect_with_get_params(
            'components.archival_storage.views.search',
            query='',
            field='',
            type=''
        )

    # get string of URL parameters that should be passed along when paging
    search_params = advanced_search.extract_url_search_params_from_request(request)

    current_page_number = int(request.GET.get('page', 1))

    # perform search
    conn = Elasticsearch(hosts=elasticSearchFunctions.getElasticsearchServerHostAndPort())

    results = None
    query = advanced_search.assemble_query(queries, ops, fields, types, search_index='aips', doc_type='aipfile')
    try:
        # use all results to pull transfer facets if not in file mode
        # pulling only one field (we don't need field data as we augment
        # the results using separate queries)
        if not file_mode:
            # Searching for AIPs still actually searches type 'aipfile', and
            # returns the UUID of the AIP the files are a part of.  To search
            # for an attribute of an AIP, the aipfile must index that
            # information about their AIP in
            # elasticSearchFunctions.index_mets_file_metadata
            # Because we're searching aips/aipfile and not aips/aip,
            # cannot using LazyPagedSequence
            results = conn.search(
                body=query,
                index='aips',
                doc_type='aipfile',
                fields='AIPUUID,sipName',
                sort='sipName:desc',
            )
        else:
            # To reduce amount of data fetched from ES, use LazyPagedSequence
            def es_pager(page, page_size):
                """
                Fetch one page of normalized aipfile entries from Elasticsearch.

                :param page: 1-indexed page to fetch
                :param page_size: Number of entries on a page
                :return: List of dicts for each entry with additional information
                """
                start = (page - 1) * page_size
                results = conn.search(
                    body=query,
                    index='aips',
                    doc_type='aipfile',
                    from_=start,
                    size=page_size,
                    fields='AIPUUID,filePath,FILEUUID',
                    sort='sipName:desc',
                )
                return search_augment_file_results(results)
            count = conn.count(index='aips', doc_type='aipfile', body={'query': query['query']})['count']
            results = LazyPagedSequence(es_pager, items_per_page, count)

    except ElasticsearchException:
        logger.exception('Error accessing index.')
        return HttpResponse('Error accessing index.')

    if not file_mode:
        # Convert the fields info into a list of dicts like this:
        # {'uuid': AIP uuid, 'name': AIP name, 'count': count of files in AIP}
        # We need to process all the results because CreateAICForm needs to know the AIP name and UUID for all results, not just those displayed on this page
        # Cannot use facets because the ordering is not the same between facets
        aip_uuids = [elasticSearchFunctions.normalize_results_dict(r) for r in results['hits']['hits']]
        working_dict = {}
        for d in aip_uuids:
            # Use AIP UUID as the key to check if an AIP has already been seen
            if d['AIPUUID'] in working_dict:
                working_dict[d['AIPUUID']]['count'] += 1
            else:
                working_dict[d['AIPUUID']] = {
                    'name': d.get('sipName', None),
                    'uuid': d['AIPUUID'],
                    'count': 1,
                }
        aip_uuids = working_dict.values()
        page_data = helpers.pager(aip_uuids, items_per_page, current_page_number)
        page_data.object_list = search_augment_aip_results(conn, page_data.object_list)
        logger.debug('AIC form results: %s', aip_uuids)
        aic_creation_form = forms.CreateAICForm(initial={'results': aip_uuids})
    else:  # if file_mode
        page_data = helpers.pager(results, items_per_page, current_page_number)
        aic_creation_form = None

    return render(request, 'archival_storage/archival_storage_search.html',
        {
            'file_mode': file_mode,
            'show_aics': show_aics,
            'checked_if_in_file_mode': checked_if_in_file_mode,
            'aic_creation_form': aic_creation_form,
            'results': page_data.object_list,
            'search_params': search_params,
            'page': page_data,
        }
    )

def search_augment_aip_results(conn, aips):
    new_aips = []
    for original_aip_info in aips:
        query = {
            "query": {
                "term": {
                    "uuid": original_aip_info['uuid']
                }
            }
        }
        documents = conn.search(
            body=query,
            index='aips',
            doc_type='aip',
            fields='name,size,created,status,AICID,isPartOf,countAIPsinAIC')
        aip = {}
        if documents['hits']['hits']:
            aip_info = documents['hits']['hits'][0]

            # Supplement the AIP dict with additional information from ES
            aip = elasticSearchFunctions.normalize_results_dict(aip_info)
            aip['uuid'] = original_aip_info['uuid']
            aip['count'] = original_aip_info['count']
            if 'isPartOf' not in aip:
                aip['isPartOf'] = ''
            if 'AICID' not in aip:
                aip['AICID'] = ''
            if 'countAIPsinAIC' not in aip:
                aip['countAIPsinAIC'] = '(unknown)'
            if 'size' in aip:
                aip['size'] = '{0:.2f} MB'.format(aip['size'])

            # TODO is there a more reliable way to determine package type?
            if 'AIC#' in aip['AICID']:
                aip['type'] = 'AIC'
            else:
                aip['type'] = 'AIP'
            if 'status' in aip:
                aip['status'] = AIP_STATUS_DESCRIPTIONS[aip['status']]
            else:
                aip['status'] = 'Stored'

            aip['document_id_no_hyphens'] = aip_info['_id'].replace('-', '____')
        else:
            aip['name'] = '(data missing)'

        new_aips.append(aip)
    return new_aips

def search_augment_file_results(raw_results):
    modifiedResults = []

    for item in raw_results['hits']['hits']:
        if 'fields' not in item:
            continue

        clone = {k: v[0] for k,v in item['fields'].copy().iteritems()}

        # try to find AIP details in database
        try:
            # get AIP data from ElasticSearch
            aip = elasticSearchFunctions.connect_and_get_aip_data(clone['AIPUUID'])

            # augment result data
            clone['sipname'] = aip['fields']['name'][0]
            clone['fileuuid'] = clone['FILEUUID']
            clone['href'] = aip['fields']['filePath'][0].replace(AIPSTOREPATH + '/', "AIPsStore/")

        except:
            aip = None
            clone['sipname'] = False

        clone['filename'] = os.path.basename(clone['filePath'])
        clone['document_id'] = item['_id']
        clone['document_id_no_hyphens'] = item['_id'].replace('-', '____')

        modifiedResults.append(clone)

    return modifiedResults


def create_aic(request, *args, **kwargs):
    aic_form = forms.CreateAICForm(request.POST or None)
    if aic_form.is_valid():
        results = ast.literal_eval(aic_form.cleaned_data['results'])
        logger.info("AIC AIP info: {}".format(results))

        # Create files in staging directory with AIP information
        shared_dir = helpers.get_server_config_value('sharedDirectory')
        staging_dir = os.path.join(shared_dir, 'tmp')

        # Create SIP (AIC) directory in staging directory
        temp_uuid = str(uuid.uuid4())
        destination = os.path.join(staging_dir, temp_uuid)
        try:
            os.mkdir(destination)
            os.chmod(destination, 0o770)
        except os.error:
            messages.error(request, "Error creating AIC")
            logger.exception("Error creating AIC: Error creating directory {}".format(destination))
            return redirect('archival_storage_index')

        # Create SIP in DB
        mcp_destination = destination.replace(shared_dir, '%sharedPath%') + '/'
        databaseFunctions.createSIP(mcp_destination, UUID=temp_uuid, sip_type='AIC')

        # Create files with filename = AIP UUID, and contents = AIP name
        for aip in results:
            filepath = os.path.join(destination, aip['uuid'])
            with open(filepath, 'w') as f:
                os.chmod(filepath, 0o660)
                f.write(str(aip['name']))

        return redirect('components.ingest.views.aic_metadata_add', temp_uuid)
    else:
        messages.error(request, "Error creating AIC")
        logger.error("Error creating AIC: Form not valid: {}".format(aic_form))
        return redirect('archival_storage_index')

def delete_context(request, uuid):
    prompt = 'Delete AIP?'
    cancel_url = reverse("components.archival_storage.views.overview")
    return RequestContext(request, {'action': 'Delete', 'prompt': prompt, 'cancel_url': cancel_url})

@decorators.confirm_required('archival_storage/delete_request.html', delete_context)
def aip_delete(request, uuid):
    try:
        reason_for_deletion = request.POST.get('reason_for_deletion', '')

        response = storage_service.request_file_deletion(
           uuid,
           request.user.id,
           request.user.email,
           reason_for_deletion
        )

        messages.info(request, response['message'])

        elasticSearchFunctions.connect_and_mark_deletion_requested(uuid)

    except requests.exceptions.ConnectionError:
        error_message = 'Unable to connect to storage server. Please contact your administrator.'
        messages.warning(request, error_message)
    except slumber.exceptions.HttpClientError:
         raise Http404

    # It would be more elegant to redirect to the AIP storage overview page, but because
    # ElasticSearch processes updates asynchronously this would often result in the user
    # having to refresh the page to get an up-to-date result
    return render(request, 'archival_storage/delete_request_results.html', locals())

def aip_download(request, uuid):
    redirect_url = storage_service.download_file_url(uuid)
    return HttpResponseRedirect(redirect_url)

def aip_file_download(request, uuid):
    # get file basename
    file          = models.File.objects.get(uuid=uuid)
    file_basename = os.path.basename(file.currentlocation)

    # get file's AIP's properties
    sipuuid      = helpers.get_file_sip_uuid(uuid)
    aip          = elasticSearchFunctions.connect_and_get_aip_data(sipuuid)
    aip_filepath = aip['fields']['filePath'][0]

    # work out path components
    aip_archive_filename = os.path.basename(aip_filepath)

    # splittext doesn't deal with double extensions, so special-case .tar.bz2
    if aip_archive_filename.endswith('.tar.bz2'):
        subdir = aip_archive_filename[:-8]
    else:
        subdir = os.path.splitext(aip_archive_filename)[0]

    # Strip %Directory% from the path
    path_to_file_within_aip_data_dir = os.path.dirname(file.currentlocation.replace('%transferDirectory%', '').replace('%SIPDirectory%', ''))

    file_relative_path = os.path.join(
      subdir,
      'data',
      path_to_file_within_aip_data_dir,
      file_basename
    )

    redirect_url = storage_service.extract_file_url(aip['fields']['uuid'][0], file_relative_path)
    return HttpResponseRedirect(redirect_url)

def aip_pointer_file_download(request, uuid):
    redirect_url = storage_service.pointer_file_url(uuid)
    return HttpResponseRedirect(redirect_url)

def send_thumbnail(request, fileuuid):
    # get AIP location to use to find root of AIP storage
    sipuuid = helpers.get_file_sip_uuid(fileuuid)

    thumbnail_path = os.path.join(
        helpers.get_client_config_value('sharedDirectoryMounted'),
        'www',
        'thumbnails',
        sipuuid,
        fileuuid + '.jpg'
    )

    # send "blank" thumbnail if one exists:
    # Because thumbnails aren't kept in ElasticSearch they can be queried for,
    # during searches, from multiple dashboard servers.
    # Because ElasticSearch don't know if a thumbnail exists or not, this is
    # a way of not causing visual disruption if a thumbnail doesn't exist.
    if not os.path.exists(thumbnail_path):
        thumbnail_path = os.path.join(settings.BASE_PATH, 'media/images/1x1-pixel.png')

    return helpers.send_file(request, thumbnail_path)

def aips_pending_deletion():
    aip_uuids = []
    try:
        aips = storage_service.get_file_info(status='DEL_REQ')
    except Exception as e:
        # TODO this should be messages.warning, but we need 'request' here
        logger.warning("Error retrieving AIPs pending deletion: is the storage server running?  Error: {}".format(e))
    else:
        for aip in aips:
            aip_uuids.append(aip['uuid'])
    return aip_uuids

def elasticsearch_query_excluding_aips_pending_deletion(uuid_field_name):
    # add UUIDs of AIPs pending deletion, if any, to boolean query
    must_not_haves = []

    for aip_uuid in aips_pending_deletion():
        must_not_haves.append({'term': {uuid_field_name: aip_uuid}})

    if len(must_not_haves):
        query = {
            "query": {
                "bool": {
                    "must_not": must_not_haves
                }
            }
        }
    else:
        # Return a deepcopy of MATCH_ALL_QUERY because it can be modified by the
        # caller and we don't want those modifications to persist
        query = copy.deepcopy(elasticSearchFunctions.MATCH_ALL_QUERY)

    return query

def aip_file_count():
    query = elasticsearch_query_excluding_aips_pending_deletion('AIPUUID')
    return advanced_search.indexed_count('aips', ['aipfile'], query)

def total_size_of_aips(conn):
    query = elasticsearch_query_excluding_aips_pending_deletion('uuid')
    query['fields'] = 'size'
    query['facets'] = {
        'total': {
            'statistical': {
                'field': 'size'
            }
        }
    }

    results = conn.search(body=query, doc_type='aip', index='aips')
    # TODO handle the return object
    total_size = results['facets']['total']['total']
    total_size = '{0:.2f}'.format(total_size)
    return total_size

def list_display(request):
    current_page_number = int(request.GET.get('page', 1))
    logger.debug('Current page: %s', current_page_number)

    # get count of AIP files
    aip_indexed_file_count = aip_file_count()

    # get AIPs
    order_by = request.GET.get('order_by', 'name_unanalyzed')
    sort_by  = request.GET.get('sort_by', 'up')

    if sort_by == 'down':
        sort_direction = 'desc'
    else:
        sort_direction = 'asc'

    sort_specification = order_by + ':' + sort_direction
    sort_params = 'order_by=' + order_by + '&sort_by=' + sort_by

    conn = elasticSearchFunctions.connect_and_create_index('aips')

    # get list of UUIDs of AIPs that are deleted or pending deletion
    aips_deleted_or_pending_deletion = []
    should_haves = [
        {'match': {'status': 'DEL_REQ'}},
        {'match': {'status': 'DELETED'}},
    ]
    query = {
        "query": {
            "bool": {
                "should": should_haves
            }
        }
    }
    deleted_aip_results = conn.search(
        body=query,
        index='aips',
        doc_type='aip',
        fields='uuid,status'
    )
    for deleted_aip in deleted_aip_results['hits']['hits']:
        aips_deleted_or_pending_deletion.append(deleted_aip['fields']['uuid'][0])

    # Fetch results and paginate
    def es_pager(page, page_size):
        """
        Fetch one page of normalized entries from Elasticsearch.

        :param page: 1-indexed page to fetch
        :param page_size: Number of entries on a page
        :return: List of dicts for each entry, where keys and values have been cleaned up
        """
        start = (page - 1) * page_size
        results = conn.search(
            index='aips',
            doc_type='aip',
            body=elasticSearchFunctions.MATCH_ALL_QUERY,
            fields='origin,uuid,filePath,created,name,size',
            sort=sort_specification,
            size=page_size,
            from_=start,
        )
        # normalize results - each of the fields contains a single value,
        # but is returned from the ES API as a single-length array
        # e.g. {"fields": {"uuid": ["abcd"], "name": ["aip"] ...}}
        return [elasticSearchFunctions.normalize_results_dict(d) for d in results['hits']['hits']]

    items_per_page = 10
    count = conn.count(index='aips', doc_type='aip', body=elasticSearchFunctions.MATCH_ALL_QUERY)['count']
    results = LazyPagedSequence(es_pager, page_size=items_per_page, length=count)

    # Paginate
    page = helpers.pager(
        results,
        items_per_page,
        current_page_number
    )

    # process deletion, etc., and format results
    aips = []
    for aip in page.object_list:
        # If an AIP was deleted or is pending deletion, react if status changed
        if aip['uuid'] in aips_deleted_or_pending_deletion:
            # check with storage server to see current status
            api_results = storage_service.get_file_info(uuid=aip['uuid'])
            try:
                aip_status = api_results[0]['status']
            except IndexError:
                # Storage service does not know about this AIP
                # TODO what should happen here?
                logger.info("AIP not found in storage service: {}".format(aip))
                continue

            # delete AIP metadata in ElasticSearch if AIP has been deleted from the
            # storage server
            # TODO: handle this asynchronously
            if aip_status == 'DELETED':
                elasticSearchFunctions.delete_aip(aip['uuid'])
                elasticSearchFunctions.connect_and_delete_aip_files(aip['uuid'])
            elif aip_status != 'DEL_REQ':
                # update the status in ElasticSearch for this AIP
                elasticSearchFunctions.connect_and_mark_stored(aip['uuid'])
        else:
            aip_status = 'UPLOADED'

        # Tweak AIP presentation and add to display array
        if aip_status != 'DELETED':
            aip['status'] = AIP_STATUS_DESCRIPTIONS[aip_status]

            try:
                size = '{0:.2f} MB'.format(float(aip['size']))
            except (TypeError, ValueError):
                size = 'Removed'

            aip['size'] = size

            aip['href'] = aip['filePath'].replace(AIPSTOREPATH + '/', "AIPsStore/")
            aip['date'] = aip['created']

            aips.append(aip)

    total_size = total_size_of_aips(conn)

    return render(request, 'archival_storage/archival_storage.html',
        {
            'total_size': total_size,
            'aip_indexed_file_count': aip_indexed_file_count,
            'aips': aips,
            'page': page,
            'search_params': sort_params,
        }
    )

def document_json_response(document_id_modified, type):
    document_id = document_id_modified.replace('____', '-')
    conn = httplib.HTTPConnection(elasticSearchFunctions.getElasticsearchServerHostAndPort())
    conn.request("GET", "/aips/" + type + "/" + document_id)
    response = conn.getresponse()
    data = response.read()
    pretty_json = json.dumps(json.loads(data), sort_keys=True, indent=2)
    return HttpResponse(pretty_json, content_type='application/json')

def file_json(request, document_id_modified):
    return document_json_response(document_id_modified, 'aipfile')

def aip_json(request, document_id_modified):
    return document_json_response(document_id_modified, 'aip')
