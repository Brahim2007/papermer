function keywords(ele) {
  addKeyword($(ele).parent().siblings("#input_kw").val().split(","));
}
function onPress(e,ele,opt) {
    if (e.keyCode == 13) {
      if(opt == 'kw'){
        addKeyword($(ele).val().split(","));
      }
      else if (opt === 'au') {
        addAuthor($(ele).val())
      }
    }
}
function addKeyword(keywords) {

  keywords.map((item,i)=>{
    if(item!==''){
      $(".keywords").append(`<span class='bg-secondary text-light ml-2 rounded'><span class='ml-2'>${item}<button kw='${item}' class='ml-2 btn btn-secondary btn-sm' onclick='removeKw(this)'>x</button></span></span>`)
      $.ajax({
        type:"POST",url:'/add_or_remove_kw/',
        data:{"data":JSON.stringify({"keywords":item}),"csrfmiddlewaretoken":csrf_token,"add":1},
        success:()=>{
          console.log("done");
        }
      })
    }
  })

}

function removeKw(ele){
  $(ele).parent().parent().remove()

  $.ajax({
    type:"POST",url:'/add_or_remove_kw/',
    data:{"data":JSON.stringify({"keywords":$(ele).attr('kw')}),"csrfmiddlewaretoken":csrf_token,"add":0},
    success:()=>{
    }
  })
}

function addTag(ele) {

  $.ajax({
    type: 'POST',
    url: "/add_remove_topic/",
    data: {add: 1,tag: $(ele).attr("subd"),csrfmiddlewaretoken: csrf_token},
    success: (res)=>{
      if($(".user_tags").find(`a[subd='${$(ele).attr("subd")}']`).length == 0){
        $(".user_tags").append(`
        <a class="d-flex user_tag" role="button" class="btn btn-outline-info" subd=${$(ele).attr("subd")}>
          ${$(ele).attr("subd")}
          <button class="btn btn-white ml-auto remove_tag" disc='${$(ele).attr("disc")}' subd='${$(ele).attr("subd")}' onclick="removeYourTopic(this)">
            <i class="fas fa-thumbtack"></i>
          </button>
        </a>`
        )
      }
    },
  })
}
function removeYourTopic(ele) {
  $.ajax({
    type: 'POST',
    url: "/add_remove_topic/",
    data: {add: 0,tag: $(ele).attr("subd"),csrfmiddlewaretoken: csrf_token},
    success: (res)=>{
      $(ele).parent().remove()
    },
  })
}
function author(ele) {
  addAuthor($(ele).parent().siblings("#input_au").val())
}
function addAuthor(name) {

  $(".authors").append(`<span class='bg-secondary text-light ml-2 rounded'><span class='ml-2'>${name}<button au='${name}' class='ml-2 btn btn-secondary btn-sm' onclick='removeKw(this)'>x</button></span></span>`)
  $.ajax({
    type:"POST",url:'/add_or_remove_author/',
    data:{"data":JSON.stringify({"authors":name}),"csrfmiddlewaretoken":csrf_token,"add":1},
  })
}
function removeAuthor(ele){
  $(ele).parent().parent().remove()

  $.ajax({
    type:"POST",url:'/add_or_remove_author/',
    data:{"data":JSON.stringify({"authors":$(ele).attr('au')}),"csrfmiddlewaretoken":csrf_token,"add":0},
  })
}
