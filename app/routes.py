from app import app, db, text
from app.models import User, Subscribe, Download
import json, os
from flask import render_template, flash, redirect, url_for, request, jsonify
from app.forms import LoginForm, RegistrationForm, SearchForm, JumpForm
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.urls import url_parse
from datetime import datetime
from time import time
import requests
from config import Config
from hashlib import md5


def get_response(url):
    i = 0
    while i < 5:
        js = None
        try:
            data = requests.get(url).text
            js = json.loads(data)
            break
        except:
            i += 1
    return js


@app.before_request
def before_request():
    if current_user.is_authenticated:
        current_user.last_seen = datetime.utcnow()
        current_user.user_ip = request.headers.environ.get('REMOTE_ADDR')
        current_user.user_agent = request.headers.environ.get('HTTP_USER_AGENT')
        # 教程上说不需要加这一行，亲测需要
        db.session.add(current_user)
        db.session.commit()


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        u = User.query.filter_by(name=form.username.data).first()
        if u is None or not u.check_password(form.password.data):
            flash('登录失败')
            return redirect('login')
        login_user(u, remember=form.remember_me.data)
        # 网页回调，使用户登录后返回登录前页面
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).decode_netloc() != '':
            next_page = url_for('index')
        return redirect(next_page)
    return render_template('login.html', title='登录', form=form)


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        u = User(name=form.username.data)
        u.set_password(form.password.data)
        db.session.add(u)
        db.session.commit()
        flash('注册成功')
        return redirect(url_for('login'))
    return render_template('register.html', form=form, title='注册')


@app.route('/', methods=['GET', 'POST'])
@app.route('/index', methods=['GET', 'POST'])
# @login_required
def index():
    dic = {}

    # 获取订阅信息
    if current_user.is_authenticated:
        dic['subscribe'] = []
        for s in current_user.subscribing:
            js = get_response('http://api.zhuishushenqi.com/book/' + s.book_id)
            dic['subscribe'].append({
                'title': js['title'],
                '_id': s.book_id,
                'last_chapter': js['lastChapter'],
                'updated': js['updated']
            })
    # 获取榜单信息
    # todo

    # 获取分类
    data = get_response('http://api.zhuishushenqi.com/cats/lv2/statistics')
    # 预分组
    # data['male'] = [data['male'][i:i + 3] for i in range(0, len(data['male']), 3)]
    # data['female'] = [data['female'][i:i + 3] for i in range(0, len(data['female']), 3)]
    # data['press'] = [data['press'][i:i + 3] for i in range(0, len(data['press']), 3)]
    dic['classify'] = data

    # 搜索框
    form = SearchForm()
    if form.validate_on_submit():
        data = get_response('http://api.zhuishushenqi.com/book/fuzzy-search/?query=' + form.search.data)
        lis = []
        for book in data.get('books'):
            lis.append(book)
        return render_template('book_list.html', data=lis, title='搜索结果', form=form)

    return render_template('index.html', data=dic, form=form, title='首页', limit=Config.CHAPTER_PER_PAGE)


@app.route('/subscribe/')
@login_required
def subscribe():
    _id = request.args.get('id')
    js = get_response('http://api.zhuishushenqi.com/book/' + _id)
    name = js.get('title')
    if not name:
        flash('这本书不存在')
        return redirect(url_for('index'))

    data = get_response('http://api.zhuishushenqi.com/toc?view=summary&book=' + _id)

    s = Subscribe(user=current_user, book_id=_id, book_name=name, source_id=data[1]['_id'], chapter=0)
    db.session.add(s)
    db.session.commit()
    flash('订阅成功')
    next_page = request.args.get('next')
    if not next_page or url_parse(next_page).decode_netloc() != '':
        next_page = url_for('index')
    return redirect(next_page)


@app.route('/unsubscribe/')
@login_required
def unsubscribe():
    _id = request.args.get('id')
    s = current_user.subscribing.filter(Subscribe.book_id == _id).first()
    db.session.delete(s)
    db.session.commit()
    flash('取消订阅成功')
    next_page = request.args.get('next')
    if not next_page or url_parse(next_page).decode_netloc() != '':
        next_page = url_for('index')
    return redirect(next_page)


@app.route('/chapter/<source_id>', methods=['GET', 'POST'])
def chapter(source_id):
    page = request.args.get('page')
    book_id = request.args.get('book_id')
    data = get_response('http://api.zhuishushenqi.com/toc/{0}?view=chapters'.format(source_id))
    lis = []
    l = []
    chap = data.get('chapters')
    form = JumpForm()
    if form.validate_on_submit():  # 必须使用post方法才能正产传递参数
        page = form.page.data
    page_count = int(len(chap) / Config.CHAPTER_PER_PAGE)
    if len(chap) % Config.CHAPTER_PER_PAGE == 0:
        page_count -= 1
    if page is not None:
        page = int(page)
        if page > page_count:
            page = page_count
        lis = chap[page * Config.CHAPTER_PER_PAGE:(page + 1) * Config.CHAPTER_PER_PAGE]
        i = 0
    for c in lis:
        l.append({
            'index': page * Config.CHAPTER_PER_PAGE + i,
            'title': c.get('title')
        })
        i += 1

    if form.validate_on_submit():
        return render_template('chapter.html', data=l, title='章节列表', page_count=page_count, page=form.page.data,
                               source_id=source_id,
                               book_id=book_id, form=form)

    return render_template('chapter.html', data=l, title='章节列表', page_count=page_count, page=page, source_id=source_id,
                           book_id=book_id, form=form)


@app.route('/read/', methods=['GET'])
# @login_required
def read():
    index = int(request.args.get('index'))
    source_id = request.args.get('source_id')
    book_id = request.args.get('book_id')
    data = get_response('http://api.zhuishushenqi.com/toc/{0}?view=chapters'.format(source_id))
    page = int(index / Config.CHAPTER_PER_PAGE)
    chap = data.get('chapters')
    title = chap[index]['title']
    url = chap[index]['link']
    # chapter_url = Config.CHAPTER_DETAIL.format(url.replace('/', '%2F').replace('?', '%3F'))
    # data = get_response(chapter_url)
    # if not data:
    #     body = '检测到阅读接口发生故障，请刷新页面或稍后再试'
    # else:
    #     if data['ok']:
    #         body = data.get('chapter').get('cpContent')
    #     else:
    #         body = '此来源暂不可用，请换源'
    #     if not body:
    #         body = data.get('chapter').get('body')
    # lis = body.split('\n')
    # li = []
    # for l in lis:
    #     if l != '' and l != '\t':
    #         li.append(l)
    li = get_text(url)

    if current_user.is_authenticated:
        s = Subscribe.query.filter(Subscribe.book_id == book_id, Subscribe.user == current_user).first()
        if s:
            s.chapter = index
            s.source_id = source_id
            s.time = datetime.utcnow()
            db.session.commit()

    return render_template('read.html', body=li, title=title, next=(index + 1) if len(chap) - index > 1 else None,
                           pre=(index - 1) if index > 0 else None,
                           book_id=book_id, page=page, source_id=source_id)


def get_text(url):
    chapter_url = Config.CHAPTER_DETAIL.format(url.replace('/', '%2F').replace('?', '%3F'))
    data = get_response(chapter_url)
    if not data:
        body = '检测到阅读接口发生故障，请刷新页面或稍后再试'
    else:
        if data['ok']:
            body = data.get('chapter').get('cpContent')
        else:
            body = '此来源暂不可用，请换源'
        if not body:
            body = data.get('chapter').get('body')
    lis = body.split('\n')
    li = []
    for l in lis:
        if l != '' and l != '\t':
            li.append(l)
    return li


# @app.route('/search/', methods=['GET', 'POST'])
# def search():
#     form = SearchForm()
#     if form.validate_on_submit():
#         data = get_response('http://api.zhuishushenqi.com/book/fuzzy-search/?query=' + form.search.data)
#         lis = []
#         for book in data.get('books'):
#             lis.append(book)
#         return render_template('book_list.html', data=lis, title='搜索结果')
#     return render_template('book_list.html', form=form, title='搜索')


UTC_FORMAT = '%Y-%m-%dT%H:%M:%S.%fZ'
LOCAL_FORMAT = '%Y-%m-%d %H:%M:%S'


def utc2local(utc_st):
    now_stamp = time()
    local_time = datetime.fromtimestamp(now_stamp)
    utc_time = datetime.utcfromtimestamp(now_stamp)
    offset = local_time - utc_time
    local_st = utc_st + offset
    return local_st


def local2utc(local_st):
    time_struct = time.mktime(local_st.timetuple())
    utc_st = datetime.datetime.utcfromtimestamp(time_struct)
    return utc_st


@app.route('/book_detail', methods=['GET'])
def book_detail():
    book_id = request.args.get('book_id')
    data = get_response('http://api.zhuishushenqi.com/book/' + book_id)
    t = data['updated']  # = datetime(data['updated']).strftime('%Y-%m-%d %H:%M:%S')
    t = datetime.strptime(t, '%Y-%m-%dT%H:%M:%S.%fZ')
    data['updated'] = utc2local(t).strftime('%Y-%m-%d %H:%M:%S')
    lis = data.get('longIntro').split('\n')
    data['longIntro'] = lis
    lastIndex = None
    # can_download = False
    if current_user.is_authenticated:
        # can_download = current_user.can_download
        s = current_user.subscribing.filter(Subscribe.book_id == book_id).first()
        if s:
            data['is_subscribe'] = True
            source_id = s.source_id
            c = s.chapter
            if not c:
                c = 0
            data['reading'] = c
            dd = get_response('http://api.zhuishushenqi.com/toc/{0}?view=chapters'.format(source_id))
            chap = dd.get('chapters')
            if chap[-1].get('title') == data.get('lastChapter'):
                lastIndex = len(chap) - 1  # 用来标记最新章节
            # chapter_title = chap[int(c)]['title']
            if int(c) + 1 > len(chap):
                data['readingChapter'] = chap[-1]['title']
            else:
                data['readingChapter'] = chap[int(c)]['title']
        else:
            dd = get_response('http://api.zhuishushenqi.com/toc?view=summary&book=' + book_id)
            for i in dd:
                if i['source'] == 'my176':
                    source_id = i['_id']
                    break
    else:
        dd = get_response('http://api.zhuishushenqi.com/toc?view=summary&book={0}'.format(book_id))
        source_id = dd[0]['_id']

    return render_template('book_detail.html', data=data, title=data.get('title'), source_id=source_id, book_id=book_id,
                           lastIndex=lastIndex,
                           next=(int(data['reading']) + 1) if data.get(
                               'reading') is not None and lastIndex is not None and lastIndex > int(
                               data['reading']) else None)


@app.route('/source/<book_id>', methods=['GET'])
def source(book_id):
    page = request.args.get('page')
    data = get_response('http://api.zhuishushenqi.com/toc?view=summary&book=' + book_id)
    for s in data:
        t = s['updated']
        t = datetime.strptime(t, '%Y-%m-%dT%H:%M:%S.%fZ')
        s['updated'] = utc2local(t).strftime('%Y-%m-%d %H:%M:%S')
    if not page:
        page = 0
    return render_template('source.html', data=data[1:], title='换源', page=page, book_id=book_id)


@app.route('/rank', methods=['GET'])
def rank():
    gender = request.args.get('gender')
    _type = request.args.get('type')
    major = request.args.get('major')
    start = request.args.get('start')
    # limit = request.args.get('limit')
    # page = request.args.get('page')
    # tag = request.args.get('tag')
    limit = str(Config.CHAPTER_PER_PAGE)
    data = get_response(
        'http://api.zhuishushenqi.com/book/by-categories?' + (('&major=' + major) if major else '') + (
            ('&gender=' + gender) if gender else '') + (('&type=' + _type) if _type else '') + (
            ('&start=' + start) if start else '') + (('&limit=' + limit) if limit else ''))
    data = data['books']
    next_page = True
    if len(data) < Config.CHAPTER_PER_PAGE:
        next_page = False
    return render_template('rank.html', data=data, title='探索', gender=gender, type=_type, major=major, start=int(start),
                           limit=int(limit), next=next_page)


@app.route('/api/download', methods=['GET'])
@login_required
def download():
    if not current_user.is_authenticated:
        return render_template('permission_denied.html', title='权限不足')
    else:
        if not current_user.can_download:
            return render_template('permission_denied.html', title='权限不足')
    source_id = request.args.get('source_id')
    book_id = request.args.get('book_id')

    # 获取章节信息
    data = get_response('http://api.zhuishushenqi.com/toc/{0}?view=chapters'.format(source_id))
    path = os.path.join(Config.UPLOADS_DEFAULT_DEST, 'downloads')
    if not os.path.exists(path):
        os.makedirs(path)

    # 定义文件名
    fileName = md5((book_id + source_id).encode("utf8")).hexdigest()[:10] + '.txt'
    # fileName = os.path.join(path, book_title + '.txt')
    # if os.path.exists(fileName):
    #     os.remove(fileName)
    d = Download.query.filter_by(book_id=book_id, source_id=source_id).first()
    chapter_list = data.get('chapters')
    if d:
        # 截取需要下载的章节列表
        new = False
        download_list = chapter_list[d.chapter + 1:]
        book_title = d.book_name
        d.chapter = len(chapter_list) - 1
        d.time = datetime.utcnow()
    else:
        new = True
        # 获取书籍简介
        data = get_response('http://api.zhuishushenqi.com/book/' + book_id)
        book_title = data.get('title')
        author = data.get('author')
        longIntro = data.get('longIntro')
        download_list = chapter_list
        d = Download(user=current_user, book_id=book_id, source_id=source_id, chapter=len(chapter_list) - 1,
                     book_name=book_title, time=datetime.utcnow(), txt_name=fileName)

    db.session.add(d)
    db.session.commit()

    with open(os.path.join(path,fileName), 'a', encoding='gbk') as f:
        if new:
            f.writelines(
                ['    ', book_title, '\n', '\n', '    ', author, '\n', '\n', '    ', longIntro, '\n', '\n'])
        for chapter in download_list:
            title = chapter.get('title')
            li = get_text(chapter.get('link'))
            f.writelines(['\n', '    ', title, '\n', '\n'])
            for sentence in li:
                try:
                    f.writelines(['    ', sentence, '\n', '\n'])
                except:
                    pass
    return render_template('view_documents.html', title=book_title + '--下载', url=text.url(fileName),
                           book_title=book_title + '.txt')
